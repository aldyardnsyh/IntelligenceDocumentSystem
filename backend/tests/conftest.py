"""Konfigurasi test.

Test memakai stub di semua tempat yang menyentuh jaringan atau model besar:

- Embedding: stub hashing, supaya test tidak perlu mengunduh model 400 MB.
- Vector store: in-memory, supaya tidak perlu Chroma.
- Memory: in-memory, supaya tidak perlu Redis.
- LLM: mock provider yang menyalin kutipan, supaya test tidak perlu API key.

Ini bukan pemangkasan cakupan: pipeline tetap dijalankan utuh dari parsing
sampai streaming SSE. Yang diganti hanya komponen yang biayanya besar dan
deterministis.
"""

from __future__ import annotations

import os
import tempfile
from collections.abc import Iterator

import pytest

# Environment harus diset sebelum app.core.config diimpor, karena Settings
# membaca env sekali lalu di-cache.
_TMP = tempfile.mkdtemp(prefix="ida-test-")
os.environ.update(
    {
        "ACCESS_PASSCODE_SHA256": (
            # sha256("rahasia-uji")
            "9a4c1b9e05b1e6c78e0f0e8b3e3d5a2b1c0d4e6f7a8b9c0d1e2f3a4b5c6d7e8"
        ),
        "LLM_PROVIDER": "mock",
        "LLM_FALLBACK_CHAIN": "",
        "USE_LOCAL_EMBEDDING": "0",
        "CHROMA_PERSIST_DIR": os.path.join(_TMP, "chroma"),
        "SQLITE_FALLBACK_PATH": os.path.join(_TMP, "metadata.db"),
        "REDIS_URL": "",
        "SUPABASE_URL": "",
        "SUPABASE_SERVICE_KEY": "",
        "GROQ_API_KEY": "",
        "DEBUG": "true",
        "CORS_ORIGINS": "http://testserver",
    }
)

from app.core.config import Settings, get_settings  # noqa: E402
from app.core.security import hash_passcode  # noqa: E402
from app.providers.embedding import HashingEmbeddingProvider  # noqa: E402
from app.providers.mock import MockProvider  # noqa: E402
from app.repositories.sqlite_repo import SqliteRepository  # noqa: E402
from app.services.generation.generator import LLMChain  # noqa: E402
from app.services.ingestion.service import IngestionService  # noqa: E402
from app.services.memory.store import InMemoryStore  # noqa: E402
from app.services.rag_service import RagService  # noqa: E402
from app.services.retrieval.retriever import HybridRetriever  # noqa: E402
from app.services.retrieval.vector_store import InMemoryVectorStore  # noqa: E402

TEST_PASSCODE = "rahasia-uji"

SAMPLE_DOCUMENT = """Standar Operasional Prosedur: Layanan Permintaan Informasi

1. Tujuan
Standar ini mengatur cara Receiving Officer menerima dan memverifikasi
permintaan informasi yang masuk melalui Satu Pintu Layanan.

2. Ruang Lingkup
Standar ini berlaku untuk seluruh unit kerja. Prosedur ini tidak berlaku untuk
permintaan yang berkaitan dengan data pribadi pihak ketiga.

3. Definisi
3.1 Receiving Officer adalah pegawai yang ditunjuk sebagai penerima pertama.
3.2 SLA Penyelesaian adalah batas waktu maksimal penyelesaian permintaan, yaitu
dua hari kerja sejak permintaan dicatat.

4. Alur Proses
4.1 Permintaan diterima melalui formulir elektronik atau loket fisik.
4.2 Receiving Officer melakukan verifikasi kelengkapan berkas.
4.3 Berkas yang lengkap diteruskan ke unit yang diminta.
"""


@pytest.fixture
def settings() -> Settings:
    """Settings dengan passcode uji yang benar."""
    get_settings.cache_clear()
    config = Settings()
    config.access_passcode_sha256 = hash_passcode(TEST_PASSCODE)
    return config


@pytest.fixture
def repository(tmp_path) -> Iterator[SqliteRepository]:  # noqa: ANN001
    """Repository SQLite di direktori sementara per test."""
    yield SqliteRepository(str(tmp_path / "test.db"))


@pytest.fixture
def memory() -> InMemoryStore:
    return InMemoryStore()


@pytest.fixture
def embedding() -> HashingEmbeddingProvider:
    return HashingEmbeddingProvider(dimension=384)


@pytest.fixture
def store() -> InMemoryVectorStore:
    return InMemoryVectorStore()


@pytest.fixture
def retriever(store: InMemoryVectorStore) -> HybridRetriever:
    return HybridRetriever(store)


@pytest.fixture
def chain() -> LLMChain:
    return LLMChain([MockProvider(Settings())])


@pytest.fixture
def ingestion(
    settings: Settings,
    repository: SqliteRepository,
    store: InMemoryVectorStore,
    retriever: HybridRetriever,
    embedding: HashingEmbeddingProvider,
    memory: InMemoryStore,
) -> IngestionService:
    return IngestionService(settings, repository, store, retriever, embedding, memory)


@pytest.fixture
async def registered_ingestion(ingestion: IngestionService) -> IngestionService:
    """Dokumen yang lewat jalur produksi, lalu diindeks sampai selesai.

    Berbeda dari ``indexed_ingestion`` yang memanggil method internal, fixture
    ini memakai ``register`` dan ``wait_pending``, jadi jalur penjadwalan
    background task ikut teruji.
    """
    await ingestion.register("panduan.md", SAMPLE_DOCUMENT.encode("utf-8"))
    await ingestion.wait_pending()
    return ingestion


@pytest.fixture
def rag(
    settings: Settings,
    repository: SqliteRepository,
    memory: InMemoryStore,
    retriever: HybridRetriever,
    embedding: HashingEmbeddingProvider,
    chain: LLMChain,
) -> RagService:
    return RagService(settings, repository, memory, retriever, embedding, chain)


@pytest.fixture
async def indexed_ingestion(ingestion: IngestionService) -> IngestionService:
    """Ingestion service dengan satu dokumen yang sudah selesai diproses.

    Dipanggil langsung ke method internal, bukan lewat ``register``, supaya
    test tidak perlu menunggu background task.
    """
    from app.models.domain import Document, DocumentStatus
    from app.services.ingestion.parser import parse_document
    from app.services.retrieval.retriever import COLLECTION, IndexEntry
    from app.services.retrieval.vector_store import VectorRecord

    parsed = parse_document(
        "panduan.md", SAMPLE_DOCUMENT.encode("utf-8"), ingestion.settings
    )
    chunks = ingestion.to_chunks("doc_uji", ingestion.build_spans(parsed))
    embeddings = ingestion.embedding.embed_documents([chunk.content for chunk in chunks])

    ingestion.store.upsert(
        (
            VectorRecord(
                id=chunk.id,
                embedding=embedding,
                metadata={
                    "document_id": "doc_uji",
                    "document_name": "panduan.md",
                    "chunk_index": chunk.chunk_index,
                    "page_number": chunk.page_number,
                    "content": chunk.content,
                    "token_count": chunk.token_count,
                },
            )
            for chunk, embedding in zip(chunks, embeddings, strict=True)
        ),
        COLLECTION,
    )
    ingestion.repository.add_chunks(chunks, "doc_uji")
    ingestion.retriever.index(
        IndexEntry(
            chunk_id=chunk.id,
            document_id="doc_uji",
            document_name="panduan.md",
            content=chunk.content,
            chunk_index=chunk.chunk_index,
            page_number=chunk.page_number,
        )
        for chunk in chunks
    )
    ingestion.repository.add_document(
        Document(
            id="doc_uji",
            filename="panduan.md",
            size_bytes=len(SAMPLE_DOCUMENT),
            status=DocumentStatus.READY,
            uploaded_at="2026-01-01T00:00:00+00:00",
            page_count=1,
            chunk_count=len(chunks),
        )
    )
    return ingestion
