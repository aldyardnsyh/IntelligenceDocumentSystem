"""Service ingestion: parsing, chunking, embedding, dan indexing.

Pipeline ini berjalan asinkron setelah upload diterima. Endpoint upload
mengembalikan ``202 Accepted`` dan tidak menunggu sampai selesai, karena
embedding satu dokumen bisa memakan puluhan detik dan frontend sudah punya
polling status.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging

from app.core.config import Settings
from app.models.domain import Chunk, Document, DocumentStatus
from app.providers.embedding import EmbeddingProvider, build_embedding_provider
from app.repositories.sqlite_repo import MetadataRepository, new_id, utc_now
from app.services.ingestion.chunker import TextSpan, chunk_text
from app.services.ingestion.parser import ParsedDocument, ParseError, parse_document
from app.services.memory.store import ANSWER_CACHE_PREFIX, CACHE_PREFIX, MemoryStore
from app.services.retrieval.retriever import COLLECTION, HybridRetriever, IndexEntry
from app.services.retrieval.vector_store import VectorRecord, VectorStore, build_vector_store
from app.services.storage import OriginalFileStore

logger = logging.getLogger(__name__)


class IngestionService:
    """Menjalankan pipeline ingestion lengkap."""

    def __init__(
        self,
        settings: Settings,
        repository: MetadataRepository,
        store: VectorStore,
        retriever: HybridRetriever,
        embedding: EmbeddingProvider,
        memory: MemoryStore | None = None,
    ) -> None:
        self._settings = settings
        self._repository = repository
        self._store = store
        self._retriever = retriever
        self._embedding = embedding
        # Memory store dipakai untuk membersihkan cache saat dokumen dihapus.
        # Opsional supaya test bisa membangun service tanpa memory store.
        self._memory = memory
        # Berkas asli disimpan untuk pratinjau PDF. Dibuat di sini supaya
        # test bisa mengarahkannya ke direktori sementara.
        self._original_files = OriginalFileStore(settings.uploads_dir)
        # Referensi kuat ke task background. Tanpa ini, task bisa di-collect
        # garbage collector sebelum selesai dan dibatalkan di tengah jalan.
        self._tasks: set[asyncio.Task[None]] = set()
        # Task dikelompokkan per dokumen supaya ``delete`` bisa membatalkan dan
        # menunggu ingestion yang sedang jalan. Tanpa itu, pengguna menghapus
        # dokumen yang masih diproses, task lamunya tetap selesai menulis chunk
        # jadi metadata hilang, chunk yatim yang tidak ada lagi di metadata.
        self._tasks_by_document: dict[str, asyncio.Task[None]] = {}

    # Atribut dibaca-tulis dari luar (test, health check), jadi
    # diekspos sebagai properti, bukan accessed lewat ``_``.
    @property
    def settings(self) -> Settings:
        return self._settings

    @property
    def repository(self) -> MetadataRepository:
        return self._repository

    @property
    def store(self) -> VectorStore:
        return self._store

    @property
    def retriever(self) -> HybridRetriever:
        return self._retriever

    @property
    def original_files(self) -> OriginalFileStore:
        return self._original_files

    @property
    def embedding(self) -> EmbeddingProvider:
        return self._embedding

    async def register(self, filename: str, data: bytes) -> Document:
        """Daftarkan dokumen baru dengan status ``processing``.

        Fungsi ini ``async`` dengan alasan teknis yang penting:
        ``asyncio.create_task`` hanya bisa dipanggil dari thread yang sedang
        menjalankan event loop. Kalau body fungsi ini dijalankan lewat
        ``asyncio.to_thread``, pemanggilnya tidak punya loop, dan
        ``create_task`` akan melempar ``RuntimeError`` yang membuat dokumen
        menggantung selamanya di status ``processing``.

        Parsing dan penulisan metadata tetap dijalankan di thread agar event
        loop tidak terblokir, tapi penjadwalan task dilakukan di sini, di atas
        loop.
        """
        document_id = new_id("doc")

        try:
            parsed = await asyncio.to_thread(
                parse_document, filename, data, self._settings
            )
        except ParseError as exc:
            # Error yang perlu diketahui pengguna muncul di respons pertama,
            # bukan disembunyikan sampai polling menemukan kegagalan.
            document = Document(
                id=document_id,
                filename=filename,
                size_bytes=len(data),
                status=DocumentStatus.FAILED,
                uploaded_at=utc_now(),
                page_count=None,
                chunk_count=0,
                error_message=str(exc),
            )
            await asyncio.to_thread(self._repository.add_document, document)
            return document

        document = Document(
            id=document_id,
            filename=filename,
            size_bytes=len(data),
            status=DocumentStatus.PROCESSING,
            uploaded_at=utc_now(),
            page_count=parsed.page_count,
            chunk_count=0,
        )

        # Halaman kosong dilaporkan, bukan diterima diam-diam. PDF hasil pindai
        # atau sebagian korup akan terlihat "siap" padahal separuh isinya
        # tidak pernah terindeks, dan itu penyebab jawaban "tidak ditemukan"
        # yang sangat sulit ditebak.
        if parsed.empty_pages:
            shown = ", ".join(str(page) for page in parsed.empty_pages[:10])
            more = "" if len(parsed.empty_pages) <= 10 else ", ..."
            logger.warning(
                "Dokumen %s: %d halaman tidak menghasilkan teks (halaman %s%s). "
                "Isi halaman itu tidak bisa dicari.",
                document_id,
                len(parsed.empty_pages),
                shown,
                more,
            )

        await asyncio.to_thread(self._repository.add_document, document)

        # Berkas asli disimpan untuk pratinjau. Kegagalannya tidak
        # menggagalkan ingestion: isi dokumen sudah tersimpan sebagai chunk,
        # jadi dokumen tetap bisa ditanyai; yang hilang hanya pratinjau.
        await asyncio.to_thread(
            self._original_files.save, document_id, filename, data
        )

        # Selesaikan di background supaya request upload tidak tertahan.
        # Referensi disimpan, kalau tidak event loop bisa mengumpulkan task
        # yang belum selesai dan membatalkannya di tengah jalan.
        task = asyncio.create_task(self._process(document, parsed))
        self._tasks.add(task)
        self._tasks_by_document[document.id] = task

        def _discard(finished: asyncio.Task[None]) -> None:
            self._tasks.discard(finished)
            if self._tasks_by_document.get(document.id) is finished:
                self._tasks_by_document.pop(document.id, None)

        task.add_done_callback(_discard)
        return document

    async def wait_pending(self) -> None:
        """Tunggu semua ingestion yang sedang berjalan.

        Dipakai test dan shutdown, supaya tidak ada dokumen yang masih
        ``processing`` saat proses berakhir.
        """
        if self._tasks:
            await asyncio.gather(*list(self._tasks), return_exceptions=True)

    async def _process(self, document: Document, parsed: ParsedDocument) -> None:
        """Chunking, embedding, lalu tulis ke vector store dan metadata."""
        try:
            spans = await asyncio.to_thread(self.build_spans, parsed)
            chunks = self.to_chunks(document.id, spans)

            if not chunks:
                await asyncio.to_thread(
                    self._repository.update_document,
                    document.id,
                    status=DocumentStatus.FAILED,
                    error_message="Pemecahan teks tidak menghasilkan chunk yang bisa diindeks.",
                )
                return

            embeddings = await asyncio.to_thread(
                self._embedding.embed_documents, [chunk.content for chunk in chunks]
            )

            records = [
                VectorRecord(
                    id=chunk.id,
                    embedding=embedding,
                    metadata={
                        "document_id": document.id,
                        "document_name": document.filename,
                        "chunk_index": chunk.chunk_index,
                        "page_number": chunk.page_number,
                        "content": chunk.content,
                        "token_count": chunk.token_count,
                    },
                )
                for chunk, embedding in zip(chunks, embeddings, strict=True)
            ]

            await asyncio.to_thread(self._store.upsert, records, COLLECTION)
            await asyncio.to_thread(
                self._repository.add_chunks, chunks, document.id
            )
            # BM25 index dibangun di memori dan ini pekerjaan CPU+I/O.
            # Menjalankannya langsung memblokir event loop sepanjang durasi
            # dokumen besar.
            await asyncio.to_thread(
                self._retriever.index,
                [
                    IndexEntry(
                        chunk_id=chunk.id,
                        document_id=document.id,
                        document_name=document.filename,
                        content=chunk.content,
                        chunk_index=chunk.chunk_index,
                        page_number=chunk.page_number,
                    )
                    for chunk in chunks
                ],
            )

            await asyncio.to_thread(
                self._repository.update_document,
                document.id,
                status=DocumentStatus.READY,
                chunk_count=len(chunks),
                page_count=document.page_count,
            )

            # Cache jawaban yang dibuat sebelum dokumen ini ada bisa jadi
            # sudah dijawab "tidak ditemukan". Setelah dokumen masuk, jawaban
            # itu basi, dan pengguna akan menyimpulkan sistemnya tidak
            # membaca dokumen barunya.
            if self._memory is not None:
                await self._memory.delete_by_prefix(
                    f"{CACHE_PREFIX}{ANSWER_CACHE_PREFIX}"
                )
            logger.info(
                "Dokumen %s siap: %d chunk dari %s", document.id, len(chunks), document.filename
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("Ingestion %s gagal", document.id)
            await asyncio.to_thread(
                self._repository.update_document,
                document.id,
                status=DocumentStatus.FAILED,
                error_message=f"Pemrosesan gagal: {exc}",
            )

    def build_spans(self, parsed: ParsedDocument) -> list[TextSpan]:
        """Potong setiap halaman, pertahankan nomor halamannya.

        Halaman diproses terpisah supaya nomor halaman tidak hilang. Dokumen
        tanpa paginasi menghasilkan satu halaman dengan nomor ``None``, dan
        Citation Card lalu menampilkan nomor chunk.
        """
        spans: list[TextSpan] = []
        for page in parsed.pages:
            spans.extend(
                chunk_text(
                    page.text,
                    size=self._settings.chunk_size,
                    overlap=self._settings.chunk_overlap,
                    page_number=page.page_number,
                )
            )
        return spans

    @staticmethod
    def to_chunks(document_id: str, spans: list[TextSpan]) -> list[Chunk]:
        return [
            Chunk(
                id=f"{document_id}_c{index + 1}",
                document_id=document_id,
                chunk_index=index,
                content=span.content,
                page_number=span.page_number,
                token_count=span.token_estimate(),
                char_start=span.char_start,
                char_end=span.char_end,
            )
            for index, span in enumerate(spans)
        ]

    async def delete(self, document_id: str) -> None:
        """Hapus dokumen beserta chunk, indeks vektor, dan cache yang merujuknya.

        Hanya dokumen ini yang dihapus. Versi sebelumnya memanggil
        ``delete_collection`` yang menghapus seluruh koleksi, jadi menghapus
        satu dokumen membuat semua dokumen lain ikut kehilangan indeksnya tanpa
        ada jejak di UI.

        Cache query juga ikut dibersihkan. Cache disimpan per kunci
        pertanyaan, jadi tidak ada cara murah untuk tahu cache mana yang
        menyinggung dokumen ini tanpa menyimpan indeks terbalik. Untuk skala
        portofolio, menghapus seluruh cache query lebih murah dan lebih jujur
        daripada menampilkan jawaban basi dengan sitasi ke dokumen yang sudah
        tidak ada.
        """
        document = await asyncio.to_thread(self._repository.get_document, document_id)
        if document is None:
            return

        # Ingestion yang masih jalan dibatalkan lebih dulu. Kalau tidak, task
        # bisa selesai menulis chunk dan indeks setelah metadata dihapus, dan
        # dokumen itu datang kembali sebagai chunk yang tidak ada pemiliknya.
        task = self._tasks_by_document.get(document_id)
        if task is not None and not task.done():
            task.cancel()
            # CancellationError ikut tertangkap agar delete tetap lanjut ke
            # penghapusan metadata; error lain juga diabaikan karena yang
            # penting di sini hanya memastikan task tidak lagi menulis.
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task

        await asyncio.to_thread(self._repository.delete_document, document_id)
        await asyncio.to_thread(
            self._store.delete_document, document_id, COLLECTION
        )
        removed = self._retriever.remove_document(document_id)

        # Berkas aslinya ikut dibuang. Kalau tidak, disk terisi berkas yang
        # tidak lagi bisa diakses siapa pun.
        if document is not None:
            await asyncio.to_thread(
                self._original_files.delete, document_id, document.filename
            )

        purged = 0
        if self._memory is not None:
            # Hanya cache jawaban yang dibersihkan. Namespace `cache:` juga
            # dipakai counter rate limit, jadi menghapusnya seluruhnya akan
            # mereset kuota pengguna setiap kali satu dokumen dihapus.
            purged = await self._memory.delete_by_prefix(
                f"{CACHE_PREFIX}{ANSWER_CACHE_PREFIX}"
            )

        logger.info(
            "Dokumen %s dihapus: %d chunk dari indeks, %d entri cache",
            document_id,
            removed,
            purged,
        )


def build_ingestion_service(
    settings: Settings,
    repository: MetadataRepository,
    memory: MemoryStore | None = None,
) -> IngestionService:
    """Bangun service dengan dependensi dari konfigurasi."""
    store = build_vector_store(settings)
    retriever = HybridRetriever(store)
    embedding = build_embedding_provider(settings)
    return IngestionService(settings, repository, store, retriever, embedding, memory)
