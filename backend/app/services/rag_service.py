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
import time
from collections.abc import AsyncIterator
from dataclasses import asdict, dataclass, field
from typing import Literal

from app.core.config import Settings
from app.models.domain import (
    ChatMessage,
    ChatSession,
    Citation,
    MessageRole,
    QueryLog,
    RetrievalSettings,
    RetrievedChunk,
)
from app.providers.base import ProviderError
from app.providers.embedding import EmbeddingProvider
from app.repositories.sqlite_repo import MetadataRepository, new_id, utc_now
from app.services.generation.generator import LLMChain
from app.services.generation.prompts import (
    NOT_FOUND_RESPONSE,
    build_citations,
    build_context_prompt,
)
from app.services.memory.store import (
    MemoryStore,
    cache_key,
    dict_to_message,
    message_to_dict,
)
from app.services.retrieval.retriever import HybridRetriever

logger = logging.getLogger(__name__)

EventType = Literal["session", "token", "citations", "not_found", "done", "error"]


@dataclass(slots=True)
class StreamEvent:
    """Satu event SSE (FR-2.4)."""

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
    ) -> None:
        self._settings = settings
        self._repository = repository
        self._memory = memory
        self._retriever = retriever
        self._embedding = embedding
        self._chain = chain

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
    ) -> AsyncIterator[StreamEvent]:
        """Stream jawaban sebagai event SSE.

        Jalur ``not_found`` dikirim sebelum LLM dipanggil. Inilah yang
        membedakan sistem yang aman dari sistem yang mengarang.
        """
        started = time.perf_counter()
        retrieval_settings = await asyncio.to_thread(self._repository.get_settings)

        # 1. Cache (FR-4.1)
        cache_id = cache_key(question, document_ids, retrieval_settings.top_k)
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
            )
            yield StreamEvent(type="done", response_time_ms=elapsed)
            return

        # 2. Retrieval
        retrieved = await self.retrieve(question, retrieval_settings, document_ids)

        if session_id is None:
            session_id = new_id("ses")
            yield StreamEvent(type="session", session_id=session_id)

        # 3. Ambang: tidak ada yang cukup mirip, berhenti di sini.
        if not retrieved:
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
            )
            yield StreamEvent(type="done", response_time_ms=elapsed)
            return

        # 4. Prompt terikat kutipan
        history = await self._load_history(session_id)
        prompt = build_context_prompt(
            question=question,
            retrieved=retrieved,
            history=history,
            max_history=self._settings.history_message_count,
        )

        # 5. Generation
        answer_parts: list[str] = []
        try:
            async for token in self._chain.stream(prompt):
                answer_parts.append(token)
                yield StreamEvent(type="token", value=token)
        except ProviderError as exc:
            elapsed = int((time.perf_counter() - started) * 1000)
            message = "Layanan bahasa sedang tidak tersedia. Coba lagi sebentar lagi."
            logger.warning("Generasi gagal: %s", exc)
            await self._record_log(
                session_id, question, elapsed, len(retrieved), from_cache=False
            )
            yield StreamEvent(type="error", value=message, retry_after_seconds=30)
            return

        answer_text = "".join(answer_parts).strip()
        citations = build_citations(retrieved)
        elapsed = int((time.perf_counter() - started) * 1000)

        if citations:
            yield StreamEvent(type="citations", value=citations)

        if answer_text:
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
        )
        yield StreamEvent(type="done", response_time_ms=elapsed)

    # ------------------------------------------------------------- histori
    async def _load_history(self, session_id: str) -> list[tuple[str, str]]:
        """Ambil N pesan terakhir (FR-3.2)."""
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
    ) -> None:
        """Simpan ke memori sesi, metadata sesi, cache, dan log."""
        now = utc_now()
        existing = await self._memory.load_session(session_id) or []
        if not any(item.get("content") == question for item in existing):
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
            )
        session.last_active_at = now
        session.message_count = len(existing)
        self._repository.upsert_session(session)

        await self._record_log(session_id, question, elapsed, len(citations), from_cache)

    async def _record_log(
        self,
        session_id: str | None,
        question: str,
        elapsed: int,
        sources: int,
        from_cache: bool,
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
        """Hapus satu sesi: memori, metadata, dan cache-nya (FR-4.2)."""
        await self._memory.delete_session(session_id)
        return await asyncio.to_thread(self._repository.delete_session, session_id)

    async def delete_all_sessions(self) -> int:
        """Hapus seluruh sesi (FR-6.3)."""
        await self._memory.delete_by_prefix("chat:")
        return await asyncio.to_thread(self._repository.delete_all_sessions)


def _slice(text: str, size: int = 24) -> list[str]:
    """Potong teks jadi potongan supaya respons non-LLM tetap terasa streaming."""
    return [text[index : index + size] for index in range(0, len(text), size)] or [""]


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
