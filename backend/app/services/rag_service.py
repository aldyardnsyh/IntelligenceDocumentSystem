"""Service retrieval dan generasi jawaban.

Ini inti RAG-nya, dan urutannya penting:

1. Cek cache.
2. Embedding pertanyaan.
3. Retrieval hybrid (vektor + BM25).
4. Kalau tidak ada chunk yang lolos ambang, berhenti di sini. LLM tidak
   pernah dipanggil dengan konteks kosong, karena itu sumber halusinasi
   paling umum.
5. Susun prompt dengan konteks bernomor.
6. Generate dan stream.
7. Simpan ke cache, memori sesi, dan log.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from collections.abc import AsyncIterator
from dataclasses import asdict, dataclass, field
from typing import Literal

from app.core.config import Settings
from app.models.domain import (
    ChatMessage,
    ChatSession,
    Citation,
    DocumentStatus,
    MessageRole,
    QueryLog,
    RetrievalSettings,
    RetrievedChunk,
)
from app.providers.base import ProviderError
from app.providers.embedding import EmbeddingProvider
from app.repositories.sqlite_repo import MetadataRepository, new_id, utc_now
from app.services.collection_query import (
    is_collection_question,
    matches_topic,
    topic_terms,
)
from app.services.generation.generator import LLMChain
from app.services.generation.prompts import (
    NOT_FOUND_RESPONSE,
    UNGROUNDED_SYSTEM_PROMPT,
    build_citations,
    build_context_prompt,
    build_ungrounded_prompt,
)
from app.services.memory.store import (
    ANSWER_CACHE_PREFIX,
    CACHE_PREFIX,
    MemoryStore,
    cache_key,
    dict_to_message,
    message_to_dict,
)
from app.services.retrieval.retriever import HybridRetriever
from app.services.tracing import TraceContext, Tracer

logger = logging.getLogger(__name__)

EventType = Literal["session", "token", "citations", "not_found", "ungrounded", "done", "error"]


@dataclass(slots=True)
class StreamEvent:
    """Satu event SSE."""

    type: EventType
    value: object = None
    response_time_ms: int | None = None
    session_id: str | None = None
    retry_after_seconds: int | None = None

    def to_payload(self) -> dict[str, object]:
        """Serialisasi ke bentuk JSON yang dikonsumsi frontend."""
        if self.type == "token":
            return {"type": "token", "value": self.value}
        if self.type == "citations":
            # Citation adalah dataclass dengan ``slots=True``, jadi tidak punya
            # ``__dict__``. ``asdict`` satu-satunya cara yang benar; memakai
            # ``__dict__`` akan melempar AttributeError tepat di event sitasi,
            # yaitu setelah jawaban pengguna sudah terkirim.
            return {
                "type": "citations",
                "value": [asdict(citation) for citation in self.value],  # type: ignore[union-attr]
            }
        if self.type == "session":
            return {"type": "session", "session_id": self.session_id}
        if self.type == "not_found":
            return {"type": "not_found"}
        if self.type == "ungrounded":
            return {"type": "ungrounded"}
        if self.type == "error":
            return {
                "type": "error",
                "message": str(self.value),
                "retry_after_seconds": self.retry_after_seconds,
            }
        return {"type": "done", "response_time_ms": self.response_time_ms or 0}


@dataclass(slots=True)
class AnswerOutcome:
    """Ringkasan satu putaran tanya-jawab, untuk log dan cache."""

    answer: str
    citations: list[Citation]
    not_found: bool
    response_time_ms: int
    from_cache: bool = False
    provider_name: str | None = None
    trace_id: str | None = None
    used_fallback: bool = False
    metadata: dict[str, object] = field(default_factory=dict)


class RagService:
    """Pipeline tanya-jawab lengkap."""

    def __init__(
        self,
        settings: Settings,
        repository: MetadataRepository,
        memory: MemoryStore,
        retriever: HybridRetriever,
        embedding: EmbeddingProvider,
        chain: LLMChain,
        tracer: Tracer | None = None,
    ) -> None:
        self._settings = settings
        self._repository = repository
        self._memory = memory
        self._retriever = retriever
        self._embedding = embedding
        self._chain = chain
        # Opsional supaya test dan skrip yang membangun RagService manual
        # tidak wajib menyediakan tracer. Tanpa itu, trace_id selalu None,
        # perilaku yang sama seperti tracing dimatikan.
        self._tracer = tracer

    # ------------------------------------------------------------- aksesor
    # Diekspos sebagai properti supaya test dan health check tidak perlu
    # menyentuh atribut privat.

    @property
    def settings(self) -> Settings:
        return self._settings

    @property
    def repository(self) -> MetadataRepository:
        return self._repository

    @property
    def memory(self) -> MemoryStore:
        return self._memory

    @property
    def retriever(self) -> HybridRetriever:
        return self._retriever

    @property
    def embedding(self) -> EmbeddingProvider:
        return self._embedding

    @property
    def chain(self) -> LLMChain:
        return self._chain

    @chain.setter
    def chain(self, value: LLMChain) -> None:
        """Ganti rantai provider.

        Dipakai test untuk menyuntikkan provider yang pasti gagal, tanpa harus
        membangun HTTP server sungguhan. Sifatnya hanya aktif di proses yang
        sedang berjalan, jadi tidak ada jalur produksi yang menyebutnya.
        """
        self._chain = value

    # ------------------------------------------------------------- retrieval
    async def retrieve(
        self,
        question: str,
        settings: RetrievalSettings,
        document_ids: list[str] | None,
    ) -> list[RetrievedChunk]:
        """Ambil chunk yang relevan, sudah disaring ambang kemiripan."""
        embedding = await asyncio.to_thread(self._embedding.embed_query, question)
        return await asyncio.to_thread(
            self._retriever.retrieve,
            question,
            embedding,
            settings.top_k,
            settings.similarity_threshold,
            document_ids,
        )

    # ------------------------------------------------------------------ ask
    async def answer(
        self,
        question: str,
        session_id: str | None,
        document_ids: list[str] | None,
        *,
        document_id: str | None = None,
        allow_ungrounded: bool = False,
    ) -> AsyncIterator[StreamEvent]:
        """Stream jawaban sebagai event SSE.

        Jalur ``not_found`` dikirim sebelum LLM dipanggil. Inilah yang
        membedakan sistem yang aman dari sistem yang mengarang. Pengecualiannya
        adalah ``allow_ungrounded=True``: LLM menjawab dari pengetahuan
        umumnya, bukan dari dokumen, dan jawabannya dilabeli jelas sebagai
        bukan dari dokumen.
        """
        started = time.perf_counter()
        retrieval_settings = await asyncio.to_thread(self._repository.get_settings)

        # Jejak dimulai sebelum apa pun, supaya cache-hit pun tercatat.
        # Kalau tracing mati, `start_trace` mengembalikan konteks kosong dan
        # semua pemanggilan berikutnya menjadi no-op, tidak ada `if` yang
        # perlu ditulis di jalur utama.
        trace = (
            self._tracer.start_trace(
                question=question,
                session_id=session_id,
                metadata={"top_k": retrieval_settings.top_k},
            )
            if self._tracer is not None
            else TraceContext()
        )

        # 1. Cache
        #
        # `document_id` (scope chat privat) HARUS ikut di kunci. Tanpa itu,
        # pertanyaan yang sama di sesi ber-scope dokumen A bisa menyajikan
        # jawaban yang dibuat dari dokumen B, scope-nya bocor lewat cache,
        # dan jawabannya membawa sitasi dokumen yang tidak pernah dicari.
        cache_id = cache_key(
            question,
            document_ids,
            retrieval_settings.top_k,
            retrieval_settings.similarity_threshold,
            document_id,
        )
        cached = await self._memory.get_cached(cache_id)
        if cached is not None:
            answer_text = str(cached.get("answer", ""))
            citations = [_citation_from_payload(item) for item in cached.get("citations", [])]  # type: ignore[union-attr]
            not_found = bool(cached.get("not_found", False))
            elapsed = int((time.perf_counter() - started) * 1000)

            if session_id is None:
                session_id = new_id("ses")
                yield StreamEvent(type="session", session_id=session_id)

            for token in _slice(answer_text):
                yield StreamEvent(type="token", value=token)
            if not_found:
                yield StreamEvent(type="not_found")
            if citations:
                yield StreamEvent(type="citations", value=citations)

            await self._persist(
                session_id=session_id,
                question=question,
                answer=answer_text,
                citations=citations,
                not_found=not_found,
                elapsed=elapsed,
                from_cache=True,
                trace_id=trace.trace_id,
                document_id=document_id,
            )
            if self._tracer is not None:
                await asyncio.to_thread(
                    self._tracer.end_trace,
                    trace,
                    answer=answer_text,
                    citations=len(citations),
                    provider_name=None,
                    from_cache=True,
                    elapsed_ms=elapsed,
                )
            yield StreamEvent(type="done", response_time_ms=elapsed)
            return

        # 2. Retrieval. Scope dokumen (untuk chat privat per dokumen) dipetakan ke
        # filter `document_ids` di retriever, bukan dengan menyetel ulang
        # retriever global.
        effective_document_ids: list[str] | None = document_ids
        if document_id:
            effective_document_ids = [document_id]
        retrieved = await self.retrieve(question, retrieval_settings, effective_document_ids)
        if self._tracer is not None:
            await asyncio.to_thread(
                self._tracer.span_retrieval,
                trace,
                chunks=retrieved,
                threshold=retrieval_settings.similarity_threshold,
            )

        if session_id is None:
            session_id = new_id("ses")
            yield StreamEvent(type="session", session_id=session_id)

        # 3. Pertanyaan tentang koleksi, bukan tentang isi.
        #
        # "carikan dokumen terkait tiketing" tidak bisa dijawab retrieval:
        # tidak ada chunk yang "mirip" dengan pertanyaan tentang daftar
        # dokumen. Tanpa jalur ini, pertanyaannya jatuh ke mode pengetahuan
        # umum, dan model menyusun daftar buku dengan penulis, tahun, dan URL
        # yang tidak ada. Itu halusinasi paling berbahaya karena terlihat
        # kredibel.
        #
        # Yang benar: jawab dari daftar dokumen yang benar-benar tersimpan.
        if is_collection_question(question):
            async for event in self._answer_collection_question(
                question=question,
                session_id=session_id,
                document_id=document_id,
                started=started,
                trace=trace,
                history=await self._load_history(session_id),
            ):
                yield event
            return

        # 4. Ambang: tidak ada chunk yang cukup mirip.
        if not retrieved:
            history = await self._load_history(session_id)

            # Pertanyaan lanjutan sering merujuk hal yang SUDAH dijawab dari
            # dokumen di pesan sebelumnya ("berapa lama?" setelah "berapa hari
            # SLA?"). Jawabannya tetap bersumber dokumen, jadi tidak boleh
            # dilabeli "bukan dari dokumen" hanya karena retrieval putaran ini
            # kosong.
            #
            # Yang membedakan dua kasus ini adalah ada tidaknya jawaban
            # bersitasi di riwayat. Kalau ada, konteks percakapan itu yang
            # dipakai, bukan pengetahuan umum model.
            has_grounded_history = _history_has_grounded_answer(history)

            if allow_ungrounded and not has_grounded_history:
                prompt = build_ungrounded_prompt(
                    question, history, self._settings.history_message_count
                )
                ungrounded_parts: list[str] = []
                degraded = False
                # Label dikirim SEBELUM token pertama. Kalau dikirim sesudah,
                # pengguna sudah membaca jawabannya lebih dulu dan baru tahu
                # asalnya di akhir, terlambat untuk mencegah salah paham.
                yield StreamEvent(type="ungrounded")
                try:
                    # System prompt HARUS diganti. Dengan SYSTEM_PROMPT biasa
                    # (yang melarang memakai pengetahuan sendiri), model
                    # konsisten menjawab "informasi tidak ditemukan", persis
                    # kegagalan yang mode ini ada untuk mencegahnya.
                    async for chunk in self._chain.stream(
                        prompt, system=UNGROUNDED_SYSTEM_PROMPT
                    ):
                        if chunk.degraded:
                            degraded = True
                            continue
                        ungrounded_parts.append(chunk.token)
                        yield StreamEvent(type="token", value=chunk.token)
                except ProviderError as exc:
                    elapsed = int((time.perf_counter() - started) * 1000)
                    message = "Layanan bahasa sedang tidak tersedia. Coba lagi sebentar lagi."
                    logger.warning("Generasi tanpa dokumen gagal: %s", exc)
                    yield StreamEvent(type="error", value=message, retry_after_seconds=30)
                    yield StreamEvent(type="done", response_time_ms=elapsed)
                    return

                answer_text = "".join(ungrounded_parts).strip()
                elapsed = int((time.perf_counter() - started) * 1000)
                await self._persist(
                    session_id=session_id,
                    question=question,
                    answer=answer_text,
                    citations=[],
                    not_found=False,
                    elapsed=elapsed,
                    from_cache=False,
                    trace_id=trace.trace_id,
                    document_id=document_id,
                    ungrounded=True,
                )
                yield StreamEvent(type="done", response_time_ms=elapsed)
                return

            if has_grounded_history:
                # Percakapan lanjutan: retrieval putaran ini kosong, tapi
                # jawabannya sudah ada di pesan sebelumnya yang bersitasi.
                # Jawab dari riwayat itu, TANPA label ungrounded, karena
                # sumbernya tetap dokumen pengguna, bukan pengetahuan umum.
                prompt = build_context_prompt(
                    question=question,
                    retrieved=[],
                    history=history,
                    max_history=self._settings.history_message_count,
                    allow_history_only=True,
                )
                history_parts: list[str] = []
                degraded = False
                try:
                    async for chunk in self._chain.stream(prompt):
                        if chunk.degraded:
                            degraded = True
                            continue
                        history_parts.append(chunk.token)
                        yield StreamEvent(type="token", value=chunk.token)
                except ProviderError as exc:
                    elapsed = int((time.perf_counter() - started) * 1000)
                    logger.warning("Generasi dari riwayat gagal: %s", exc)
                    yield StreamEvent(
                        type="error",
                        value="Layanan bahasa sedang tidak tersedia. Coba lagi sebentar lagi.",
                        retry_after_seconds=30,
                    )
                    yield StreamEvent(type="done", response_time_ms=elapsed)
                    return

                answer_text = "".join(history_parts).strip()
                elapsed = int((time.perf_counter() - started) * 1000)
                if _is_refusal(answer_text):
                    # Model menilai riwayatnya pun tidak memuat jawaban.
                    for token in _slice(NOT_FOUND_RESPONSE):
                        yield StreamEvent(type="token", value=token)
                    yield StreamEvent(type="not_found")
                    await self._persist(
                        session_id=session_id,
                        question=question,
                        answer=NOT_FOUND_RESPONSE,
                        citations=[],
                        not_found=True,
                        elapsed=elapsed,
                        from_cache=False,
                        trace_id=trace.trace_id,
                        document_id=document_id,
                    )
                    yield StreamEvent(type="done", response_time_ms=elapsed)
                    return

                await self._persist(
                    session_id=session_id,
                    question=question,
                    answer=answer_text,
                    citations=[],
                    not_found=False,
                    elapsed=elapsed,
                    from_cache=False,
                    trace_id=trace.trace_id,
                    document_id=document_id,
                )
                yield StreamEvent(type="done", response_time_ms=elapsed)
                return

            # --- gerbang anti-halusinasi: tanpa konteks, LLM tidak dipanggil
            elapsed = int((time.perf_counter() - started) * 1000)
            for token in _slice(NOT_FOUND_RESPONSE):
                yield StreamEvent(type="token", value=token)
            yield StreamEvent(type="not_found")

            await self._persist(
                session_id=session_id,
                question=question,
                answer=NOT_FOUND_RESPONSE,
                citations=[],
                not_found=True,
                elapsed=elapsed,
                from_cache=False,
                trace_id=trace.trace_id,
                document_id=document_id,
            )
            if self._tracer is not None:
                await asyncio.to_thread(
                    self._tracer.end_trace,
                    trace,
                    answer=NOT_FOUND_RESPONSE,
                    citations=0,
                    provider_name=None,
                    from_cache=False,
                    elapsed_ms=elapsed,
                )
            yield StreamEvent(type="done", response_time_ms=elapsed)
            return

        # 5. Prompt terikat kutipan
        history = await self._load_history(session_id)
        prompt = build_context_prompt(
            question=question,
            retrieved=retrieved,
            history=history,
            max_history=self._settings.history_message_count,
        )

        # 6. Generation
        answer_parts: list[str] = []
        degraded = False
        try:
            async for chunk in self._chain.stream(prompt):
                if chunk.degraded:
                    degraded = True
                    continue
                answer_parts.append(chunk.token)
                yield StreamEvent(type="token", value=chunk.token)
        except ProviderError as exc:
            elapsed = int((time.perf_counter() - started) * 1000)
            message = "Layanan bahasa sedang tidak tersedia. Coba lagi sebentar lagi."
            logger.warning("Generasi gagal: %s", exc)
            await self._record_log(
                session_id,
                question,
                elapsed,
                len(retrieved),
                from_cache=False,
                trace_id=trace.trace_id,
            )
            if self._tracer is not None:
                await asyncio.to_thread(
                    self._tracer.end_trace,
                    trace,
                    answer=f"PROVIDER_ERROR: {exc}",
                    citations=len(retrieved),
                    provider_name=",".join(self._chain.provider_names),
                    from_cache=False,
                    elapsed_ms=elapsed,
                )
            yield StreamEvent(type="error", value=message, retry_after_seconds=30)
            return

        answer_text = _clean_answer("".join(answer_parts).strip())
        citations = build_citations(retrieved)
        elapsed = int((time.perf_counter() - started) * 1000)

        # Model bisa menyimpulkan "tidak ada di konteks" meski retrieval
        # meloloskan chunk (topiknya menyerempet tapi jawabannya tidak ada).
        # Dalam kasus itu sitasi tidak boleh dikirim: jawabannya tidak memakai
        # sumber itu, dan menampilkan sumber membuatnya terlihat bersumber
        # padahal bukan, persis kebingungan yang sitasi ada untuk mencegah.
        if _is_refusal(answer_text):
            citations = []

        if citations:
            yield StreamEvent(type="citations", value=citations)

        if answer_text and not degraded:
            # Jawaban yang terpotong karena provider gagal tidak boleh masuk
            # cache: cache akan menjadikannya jawaban "resmi" selama TTL.
            await self._memory.set_cached(
                cache_id,
                {
                    "answer": answer_text,
                    # ``asdict``, bukan ``__dict__``: Citation pakai
                    # ``slots=True`` dan tidak punya ``__dict__``.
                    "citations": [asdict(citation) for citation in citations],
                    "not_found": False,
                },
                self._settings.cache_ttl_seconds,
            )

        await self._persist(
            session_id=session_id,
            question=question,
            answer=answer_text,
            citations=citations,
            not_found=False,
            elapsed=elapsed,
            from_cache=False,
            trace_id=trace.trace_id,
            document_id=document_id,
        )
        if self._tracer is not None:
            # Nama provider tidak tersedia di sini (chain hanya mengembalikan
            # token), jadi dicatat apa adanya. Yang penting untuk debugging
            # adalah konteks dan hasilnya, bukan siapa yang menjawab.
            await asyncio.to_thread(
                self._tracer.end_trace,
                trace,
                answer=answer_text,
                citations=len(citations),
                provider_name=",".join(self._chain.provider_names),
                from_cache=False,
                elapsed_ms=elapsed,
            )
        yield StreamEvent(type="done", response_time_ms=elapsed)

    # ------------------------------------------------------------- histori
    async def _answer_collection_question(
        self,
        *,
        question: str,
        session_id: str,
        document_id: str | None,
        started: float,
        trace: TraceContext,
        history: list[tuple[str, str]],
    ) -> AsyncIterator[StreamEvent]:
        """Jawab pertanyaan tentang daftar dokumen, dari data yang tersimpan.

        Jawabannya disusun dari metadata dokumen (nama, jumlah chunk, status),
        bukan dari model. Model hanya dipakai kalau pengguna mengizinkan mode
        pengetahuan umum, dan itupun dibatasi oleh aturan yang melarang
        menyusun daftar referensi.

        Kenapa tidak memakai retrieval: pertanyaan "carikan dokumen terkait
        tiketing" tidak punya chunk yang mirip. Yang dicari adalah metadata
        dokumen, bukan isi chunk.
        """
        documents = await asyncio.to_thread(self._repository.list_documents)

        # Scope sesi tetap dihormati: sesi privat satu dokumen tidak boleh
        # tiba-tiba menjawab tentang seluruh koleksi.
        if document_id:
            documents = [item for item in documents if item.id == document_id]

        ready = [item for item in documents if item.status is DocumentStatus.READY]
        terms = topic_terms(question)

        # Cocokkan topik ke nama dokumen. Pencocokan sederhana dan bisa
        # diperiksa: nama dokumen mengandung kata kunci, atau sebaliknya.
        # Pencocokan memakai awalan kata, bukan substring penuh, supaya
        # "tiketing" menemukan "panduan-tiket-layanan.md".
        matched = (
            [item for item in ready if matches_topic(item.filename, terms)]
            if terms
            else ready
        )

        elapsed = int((time.perf_counter() - started) * 1000)

        if not documents:
            answer = (
                "Belum ada dokumen yang tersimpan. Unggah dokumen lebih dulu "
                "di halaman Dokumen, lalu tanyakan lagi."
            )
        elif not matched:
            daftar = ", ".join(item.filename for item in ready[:10]) or "belum ada"
            answer = (
                f"Tidak ada dokumen yang cocok dengan kata kunci itu. "
                f"Dokumen yang tersedia: {daftar}. "
                "Coba pakai istilah yang lebih umum, atau unggah dokumen yang "
                "Anda maksud supaya bisa ditanyai."
            )
        else:
            baris = "\n".join(
                f"- {item.filename} ({item.chunk_count} chunk)"
                for item in matched[:20]
            )
            sisa = (
                f"\n\nMasih ada {len(matched) - 20} dokumen lain yang cocok."
                if len(matched) > 20
                else ""
            )
            answer = (
                f"Dokumen yang cocok dengan kata kunci itu ada {len(matched)}:\n"
                f"{baris}{sisa}\n\n"
                "Klik salah satu di halaman Dokumen, atau pakai tombol "
                "\"Tanya dokumen ini\" untuk membatasi pencarian ke dokumen itu."
            )

        for token in _slice(answer):
            yield StreamEvent(type="token", value=token)

        await self._persist(
            session_id=session_id,
            question=question,
            answer=answer,
            citations=[],
            not_found=False,
            elapsed=elapsed,
            from_cache=False,
            trace_id=trace.trace_id,
            document_id=document_id,
        )
        yield StreamEvent(type="done", response_time_ms=elapsed)

    async def _load_history(self, session_id: str) -> list[tuple[str, str]]:
        """Ambil N pesan terakhir."""
        stored = await self._memory.load_session(session_id)
        if not stored:
            return []
        messages = [dict_to_message(item) for item in stored]
        return [(message.role.value, message.content) for message in messages]

    async def _persist(
        self,
        *,
        session_id: str,
        question: str,
        answer: str,
        citations: list[Citation],
        not_found: bool,
        elapsed: int,
        from_cache: bool,
        trace_id: str | None = None,
        document_id: str | None = None,
        ungrounded: bool = False,
    ) -> None:
        """Simpan ke memori sesi, metadata sesi, cache, dan log."""
        now = utc_now()
        existing = await self._memory.load_session(session_id) or []
        # Setiap pertanyaan adalah pesan tersendiri, meski isinya sama dengan
        # pertanyaan sebelumnya. Dedupe berbasis isi pernah dipakai di sini:
        # pertanyaan yang diulang menghasilkan satu pesan user tapi dua jawaban
        # asisten, sehingga histori yang dimuat kembali tidak berpasangan.
        existing.append(
            message_to_dict(
                ChatMessage(
                    id=new_id("msg"),
                    role=MessageRole.USER,
                    content=question,
                    created_at=now,
                )
            )
        )
        existing.append(
            message_to_dict(
                ChatMessage(
                    id=new_id("msg"),
                    role=MessageRole.ASSISTANT,
                    content=answer,
                    created_at=now,
                    citations=citations,
                    not_found=not_found,
                    ungrounded=ungrounded,
                )
            )
        )
        await self._memory.save_session(
            session_id, existing, self._settings.session_memory_ttl_seconds
        )

        session = self._repository.get_session(session_id)
        if session is None:
            # Judul otomatis dari pertanyaan pertama, dipotong rapi supaya
            # sidebar tidak penuh teks panjang.
            title = " ".join(question.split())[:60] + ("..." if len(question) > 60 else "")
            session = ChatSession(
                id=session_id,
                title=title,
                created_at=now,
                last_active_at=now,
                message_count=0,
                document_id=document_id,
            )
        session.last_active_at = now
        session.message_count = len(existing)
        self._repository.upsert_session(session)

        await self._record_log(
            session_id, question, elapsed, len(citations), from_cache, trace_id
        )

    async def _record_log(
        self,
        session_id: str | None,
        question: str,
        elapsed: int,
        sources: int,
        from_cache: bool,
        trace_id: str | None = None,
    ) -> None:
        await asyncio.to_thread(
            self._repository.add_log,
            QueryLog(
                id=new_id("log"),
                session_id=session_id,
                question=question,
                response_time_ms=elapsed,
                sources_count=sources,
                created_at=utc_now(),
                from_cache=from_cache,
                trace_id=trace_id,
            ),
        )

    # ------------------------------------------------------------- histori
    async def get_history(self, session_id: str) -> list[ChatMessage]:
        stored = await self._memory.load_session(session_id)
        return [dict_to_message(item) for item in (stored or [])]

    async def live_session_ids(self) -> list[str]:
        """ID sesi yang masih ada di memory store.

        Sidebar hanya menampilkan sesi yang ini bisa dibuka lagi. Sesi di
        database tapi sudah kedaluwarsa di memori akan menghasilkan halaman
        404, jadi menampilkannya hanya membingungkan.
        """
        return await self._memory.list_sessions()

    @property
    def provider_names(self) -> list[str]:
        """Nama provider yang aktif. Dipakai health endpoint."""
        return self._chain.provider_names

    async def memory_available(self) -> bool:
        """True kalau memory store bisa dihubungi."""
        return bool(await self._memory.ping())

    async def delete_session(self, session_id: str) -> bool:
        """Hapus satu sesi: memori, metadata, dan cache-nya."""
        await self._memory.delete_session(session_id)
        return await asyncio.to_thread(self._repository.delete_session, session_id)

    async def delete_all_sessions(self) -> int:
        """Hapus seluruh sesi."""
        await self._memory.delete_by_prefix("chat:")
        # Cache jawaban ikut dibersihkan: jawaban yang tersimpan bisa merujuk
        # dokumen yang sudah dihapus, dan mengembalikannya setelah semua sesi
        # dihapus hanya membingungkan.
        await self._memory.delete_by_prefix(f"{CACHE_PREFIX}{ANSWER_CACHE_PREFIX}")
        return await asyncio.to_thread(self._repository.delete_all_sessions)


def _clean_answer(text: str) -> str:
    r"""Bersihkan markup dan tanda pisah yang tidak pantas di jawaban.

    Prompt sudah meminta model menulis ulang dengan kalimatnya sendiri, tapi
    instruksi saja tidak cukup dapat diandalkan, terutama pada model kecil.
    Lapisan ini memastikan pengguna tidak pernah melihat `**tebal**`, `#`
    judul, garis `====`, atau em dash di jawaban, apa pun yang dilakukan
    model.

    Sengaja hanya membuang penanda dan mengganti tanda pisah, bukan mengubah
    kata: isi jawaban tetap apa adanya, jadi tidak ada risiko mengubah makna.
    """
    cleaned = text
    # Penanda tebal/miring: **teks** -> teks, __teks__ -> teks.
    cleaned = re.sub(r"\*\*(.+?)\*\*", r"\1", cleaned, flags=re.DOTALL)
    cleaned = re.sub(r"__(.+?)__", r"\1", cleaned, flags=re.DOTALL)
    # Garis pemisah dari dokumen (==== atau ----) dibuang seluruhnya.
    cleaned = re.sub(r"^[=\-]{3,}\s*$", "", cleaned, flags=re.MULTILINE)
    # Heading markdown di awal baris: "## Judul" -> "Judul".
    cleaned = re.sub(r"^#{1,6}\s+", "", cleaned, flags=re.MULTILINE)
    # Em dash dan en dash diganti koma. Tanda pisah panjang adalah penanda
    # gaya tulisan mesin, dan jawaban yang memakainya terbaca seperti
    # template, bukan seperti asisten yang sedang menjelaskan.
    cleaned = cleaned.replace(" \u2014 ", ", ").replace("\u2014", ", ")
    cleaned = cleaned.replace(" \u2013 ", ", ").replace("\u2013", ", ")
    # Tanda hubung ganda sebagai pengganti tanda pisah juga dibuang.
    cleaned = re.sub(r"\s-{2,}\s", ", ", cleaned)
    # Koma beruntun dirapikan.
    cleaned = re.sub(r",\s*,", ",", cleaned)
    # Baris yang jadi kosong beruntun dirapikan.
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def _history_has_grounded_answer(history: list[tuple[str, str]]) -> bool:
    """True kalau ada jawaban asisten di riwayat yang bersumber dokumen.

    Dipakai untuk membedakan dua situasi yang terlihat sama dari luar:

    - Pertanyaan lanjutan tentang hal yang sudah dijawab dari dokumen
      ("berapa lama?" setelah "berapa hari SLA?"). Jawabannya tetap bersumber
      dokumen, jadi tidak boleh dilabeli "bukan dari dokumen".
    - Pertanyaan baru yang benar-benar tidak ada di dokumen. Ini yang pantas
      mendapat label ungrounded kalau pengguna mengizinkan.

    Yang diperiksa: ada jawaban asisten yang **bukan penolakan** dan cukup
    panjang untuk memuat isi. Ambangnya sengaja rendah (40 karakter) karena
    jawaban benar bisa singkat ("Dua hari kerja sejak permintaan dicatat")
    dan jawaban yang lebih pendek dari itu biasanya memang penolakan.
    """
    for role, content in history:
        if role != "assistant":
            continue
        text = content.strip()
        if len(text) < 40:
            continue
        if _is_refusal(text):
            continue
        return True
    return False


def _slice(text: str, size: int = 24) -> list[str]:
    """Potong teks jadi potongan supaya respons non-LLM tetap terasa streaming."""
    return [text[index : index + size] for index in range(0, len(text), size)] or [""]


#: Frasa yang menandakan model menyimpulkan jawabannya tidak ada di konteks.
#: Sengaja diperiksa di kode, bukan diserahkan ke model: yang menentukan
#: apakah sitasi dikirim harus aturan yang bisa diuji, bukan kebetulan kata
#: yang dipilih model.
_REFUSAL_MARKERS = (
    "tidak ditemukan",
    "tidak ada dalam dokumen",
    "tidak ada di dalam dokumen",
    "tidak disebutkan",
    "tidak dijelaskan",
    "informasi tidak tersedia",
    "tidak tersedia dalam dokumen",
    "tidak memuat informasi",
    "not found",
)


def _is_refusal(answer: str) -> bool:
    """True kalau jawaban pada dasarnya menyatakan "tidak ada di dokumen".

    Dipakai untuk menahan sitasi. Jawaban seperti itu tidak memakai sumber
    mana pun, jadi menampilkan sumber di bawahnya membuat pengguna mengira
    informasi itu ada di dokumen.
    """
    lowered = answer.strip().lower()
    if not lowered:
        return False
    # Jawaban panjang yang kebetulan memuat frasa itu biasanya tetap
    # menjawab; hanya jawaban pendek yang memang penolakan murni.
    if len(lowered) > 240:
        return False
    return any(marker in lowered for marker in _REFUSAL_MARKERS)


def _citation_from_payload(payload: dict[str, object]) -> Citation:
    page = payload.get("page_number")
    return Citation(
        document_id=str(payload.get("document_id", "")),
        document_name=str(payload.get("document_name", "")),
        page_number=int(page) if isinstance(page, int) else None,
        chunk_index=int(payload.get("chunk_index", 0)),
        excerpt=str(payload.get("excerpt", "")),
        score=float(payload.get("score", 0.0)),
    )
