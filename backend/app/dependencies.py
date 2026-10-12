"""Dependency injection FastAPI.

Semua service dibangun satu kali saat aplikasi start, lalu dipakai bersama.
Membangun embedding model per request akan sangat lambat, jadi inisialisasi
wajib terjadi di lifespan, bukan di dalam handler.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging

from app.core.config import Settings, get_settings
from app.providers.embedding import build_embedding_provider
from app.repositories.sqlite_repo import MetadataRepository, SqliteRepository
from app.services.generation.generator import LLMChain, build_chain
from app.services.ingestion.service import IngestionService
from app.services.memory.rate_limit import RateLimiter
from app.services.memory.store import MemoryStore, build_memory_store
from app.services.rag_service import RagService
from app.services.retrieval.retriever import HybridRetriever
from app.services.retrieval.vector_store import VectorStore, build_vector_store
from app.services.tracing import Tracer

logger = logging.getLogger(__name__)

_settings: Settings | None = None
_repository: MetadataRepository | None = None
_memory: MemoryStore | None = None
_store: VectorStore | None = None
_retriever: HybridRetriever | None = None
_ingestion: IngestionService | None = None
_rag: RagService | None = None
_chain: LLMChain | None = None
_limiter: RateLimiter | None = None
_tracer: Tracer | None = None


def init_services(app_settings: Settings | None = None) -> None:
    """Bangun semua service. Dipanggil sekali di lifespan."""
    global _settings, _repository, _memory, _store, _retriever
    global _ingestion, _rag, _chain, _limiter, _tracer

    _settings = app_settings or get_settings()

    if _settings.is_sqlite_mode:
        _repository = SqliteRepository(_settings.sqlite_fallback_path, defaults=_settings)
    else:
        from app.repositories.supabase_repo import SupabaseRepository  # noqa: PLC0415

        _repository = SupabaseRepository(_settings)

    _memory = build_memory_store(_settings)
    _store = build_vector_store(_settings)
    _retriever = HybridRetriever(_store)

    embedding = build_embedding_provider(_settings)
    # Memory store diteruskan supaya penghapusan dokumen bisa ikut membersihkan
    # cache query yang menyinggung dokumen tersebut.
    _ingestion = IngestionService(
        _settings, _repository, _store, _retriever, embedding, _memory
    )

    # `build_chain` dipakai (bukan `LLMChain(...)` langsung) supaya
    # `LLM_MAX_RETRIES` benar-benar dibaca. Dipanggil langsung, nilainya
    # diabaikan tanpa satu pun tanda bahwa konfigurasi itu tidak berlaku.
    _chain = build_chain(_settings)
    # Tracer dibuat di sini supaya satu instans dipakai seluruh query.
    # Kalau tracing mati, objeknya tetap ada tapi semua method-nya no-op.
    _tracer = Tracer(_settings)
    _rag = RagService(
        _settings, _repository, _memory, _retriever, embedding, _chain, _tracer
    )
    _limiter = RateLimiter(_memory, _settings)

    # Bangun ulang indeks retrieval dari metadata yang tersimpan.
    #
    # Tanpa langkah ini, indeks BM25 dan peta metadata hanya terisi oleh
    # dokumen yang diunggah selama proses ini berjalan. Setelah container
    # di-restart, dokumennya masih ada di SQLite dan Chroma, tapi retriever
    # tidak tahu apa pun, sehingga setiap pertanyaan dijawab "tidak
    # ditemukan" tanpa satu pun error di log.
    #
    # Kegagalan rebuild tidak boleh menggagalkan startup: aplikasi yang bisa
    # menjawab dokumen baru masih lebih berguna daripada yang tidak jalan
    # sama sekali. Tapi kondisinya harus dicatat keras, karena itu berarti
    # corpus lama tidak bisa dicari.
    try:
        restored = _retriever.rebuild(_index_entries(_repository))
    except Exception:  # noqa: BLE001
        logger.exception(
            "Gagal membangun ulang indeks retrieval. Dokumen yang sudah diindeks "
            "sebelum restart tidak akan bisa dicari sampai diindeks ulang."
        )
    else:
        if restored:
            logger.info("Indeks retrieval dipulihkan: %d chunk.", restored)

    logger.info(
        "Layanan siap: repository=%s memory=%s vector=%s llm=%s",
        _repository.name,
        _memory.name,
        _store.name,
        ",".join(_chain.provider_names),
    )
    # Detail komponen hanya dicatat di log server, bukan dikirim lewat
    # endpoint publik /health. Log hanya bisa dibaca operator, sedangkan
    # /health bisa dipanggil siapa pun.
    logger.info(
        "Detail komponen: tracing=%s vector_persistent=%s embedding=%s",
        "aktif" if _tracer.enabled else "mati",
        _store.persistent,
        _settings.embedding_model if _settings.use_local_embedding else "hashing-fallback",
    )


def _index_entries(repository: MetadataRepository) -> list:
    """Chunk tersimpan menjadi entri indeks untuk retriever."""
    from app.services.retrieval.retriever import IndexEntry  # noqa: PLC0415

    return [
        IndexEntry(
            chunk_id=chunk.id,
            document_id=chunk.document_id,
            document_name=chunk.document_name or "dokumen",
            content=chunk.content,
            chunk_index=chunk.chunk_index,
            page_number=chunk.page_number,
        )
        for chunk in repository.all_chunks()
    ]


def shutdown_services() -> None:
    """Kosongkan referensi service. Dipanggil saat aplikasi berhenti."""
    global _settings, _repository, _memory, _store, _retriever
    global _ingestion, _rag, _chain, _limiter, _tracer

    # Flush antrean Langfuse sebelum referensinya hilang. Tanpa ini, jejak
    # dari beberapa query terakhir tidak pernah sampai ke server.
    if _tracer is not None:
        try:
            _tracer.flush()
        except Exception:  # noqa: BLE001
            logger.exception("Gagal flush tracer saat shutdown")

    # Tutup koneksi HTTP provider. Kliennya dipakai bersama antar request,
    # jadi proses yang berhenti tanpanya meninggalkan socket terbuka sampai
    # OS membersihkannya.
    if _chain is not None:
        for provider in _chain.providers:
            closer = getattr(provider, "aclose", None)
            if closer is None:
                continue
            # Kegagalan menutup koneksi tidak boleh menggagalkan shutdown.
            with contextlib.suppress(Exception):
                asyncio.run(closer())

    _settings = None
    _repository = None
    _memory = None
    _store = None
    _retriever = None
    _ingestion = None
    _rag = None
    _chain = None
    _limiter = None
    _tracer = None


# --------------------------------------------------------------- accessors


def get_app_settings() -> Settings:
    """Settings aktif. Dipakai handler lewat ``Depends``."""
    if _settings is None:
        init_services()
    assert _settings is not None
    return _settings


def get_repository() -> MetadataRepository:
    if _repository is None:
        init_services()
    assert _repository is not None
    return _repository


def get_memory() -> MemoryStore:
    if _memory is None:
        init_services()
    assert _memory is not None
    return _memory


def get_rag() -> RagService:
    if _rag is None:
        init_services()
    assert _rag is not None
    return _rag


def get_ingestion() -> IngestionService:
    if _ingestion is None:
        init_services()
    assert _ingestion is not None
    return _ingestion


def get_rate_limiter() -> RateLimiter:
    if _limiter is None:
        init_services()
    assert _limiter is not None
    return _limiter


def get_tracer() -> Tracer:
    """Tracer aktif. Dipakai health check untuk melaporkan status tracing."""
    if _tracer is None:
        init_services()
    assert _tracer is not None
    return _tracer


__all__ = [
    "get_app_settings",
    "get_ingestion",
    "get_memory",
    "get_rag",
    "get_rate_limiter",
    "get_repository",
    "get_tracer",
    "init_services",
    "shutdown_services",
]
