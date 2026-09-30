"""Skema kontrak API.

Bentuk di sini adalah kontrak publik yang dikonsumsi ``frontend/``. Rinciannya
ada di ``API-CONTRACT.md``. Ubah di sini hanya kalau kontrak memang berubah,
lalu perbarui juga dokumen itu.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.models.domain import (
    ChatMessage,
    ChatSession,
    Chunk,
    Citation,
    Document,
    DocumentStatus,
    QueryLog,
)


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


# ------------------------------------------------------------------ auth


class PasscodeRequest(BaseModel):
    passcode: str = Field(min_length=1, max_length=256)


class PasscodeResponse(BaseModel):
    ok: Literal[True] = True
    expires_in: int


# -------------------------------------------------------------- documents


class DocumentSummary(BaseModel):
    """Metadata dokumen, tanpa daftar chunk."""

    id: str
    filename: str
    size_bytes: int
    status: DocumentStatus
    uploaded_at: str
    page_count: int | None = None
    chunk_count: int | None = None
    error_message: str | None = None


class IngestionInfo(BaseModel):
    """Parameter ingestion yang benar-benar dipakai.

    Dikirim apa adanya ke frontend supaya angka di halaman detail berasal dari
    proses nyata, bukan konstanta tebakan.
    """

    splitter: str
    chunk_size: int
    chunk_overlap: int
    embedding_model: str
    vector_store: str


class DocumentDetail(DocumentSummary):
    """Metadata plus konfigurasi ingestion. Tanpa ``chunks``.

    Chunk diambil terpisah lewat ``/documents/{id}/chunks`` supaya dokumen besar
    tidak mengirim seluruh isinya sekaligus.
    """

    ingestion: IngestionInfo


class ChunkResponse(BaseModel):
    id: str
    document_id: str
    chunk_index: int
    page_number: int | None = None
    content: str
    token_count: int | None = None


class ChunkPage(BaseModel):
    """Satu halaman hasil, dengan ``total`` hasil *setelah* filter."""

    items: list[ChunkResponse]
    total: int
    page: int
    page_size: int


class DocumentStatusResponse(BaseModel):
    id: str
    status: DocumentStatus
    chunk_count: int
    error_message: str | None = None


# ------------------------------------------------------------------- chat


class CitationResponse(BaseModel):
    document_id: str
    document_name: str
    page_number: int | None
    chunk_index: int
    excerpt: str
    score: float


class ChatQueryRequest(BaseModel):
    session_id: str | None = None
    question: str = Field(min_length=1, max_length=8000)
    document_ids: list[str] | None = None

    @field_validator("question")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("Pertanyaan tidak boleh kosong.")
        return stripped


class ChatHistoryResponse(BaseModel):
    session: ChatSessionResponse
    messages: list[ChatMessageResponse]


class ChatSessionResponse(BaseModel):
    id: str
    title: str
    created_at: str
    last_active_at: str
    message_count: int


class ChatMessageResponse(BaseModel):
    id: str
    role: Literal["user", "assistant"]
    content: str
    created_at: str
    citations: list[CitationResponse] = Field(default_factory=list)
    not_found: bool = False


class SessionRenameRequest(BaseModel):
    title: str = Field(min_length=1, max_length=80)

    @field_validator("title")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        stripped = " ".join(value.split())
        if not stripped:
            raise ValueError("Nama sesi tidak boleh kosong.")
        return stripped[:80]


# --------------------------------------------------------------- settings


class SettingsResponse(BaseModel):
    top_k: int
    similarity_threshold: float


class SettingsUpdate(BaseModel):
    """Permintaan ubah parameter retrieval.

    Sengaja **tanpa batas di sini**. Batas yang boleh diterima ditetapkan di
    ``Settings.min_top_k``/``max_top_k``, dan route yang bertanggung jawab
    meng-klem lalu mengembalikan nilai final yang aktif di respons.

    Kalau batas dipaksakan di sini, dua hal buruk terjadi: nilai di luar
    rentang ditolak dengan ``422`` sehingga route tidak pernah menjalankan
    klemnya (kode mati yang terlihat benar), dan batas yang sama tercatat di
    dua tempat sehingga mudah tidak sinkron dengan slider di frontend.
    Menaikkan batas cukup mengubah ``max_top_k`` di konfigurasi.
    """

    top_k: int | None = None
    similarity_threshold: float | None = None


# -------------------------------------------------------------- analytics


class EvalRunResponse(BaseModel):
    id: str
    precision: float | None
    faithfulness: float | None
    answer_relevance: float | None
    run_at: str


class LatencyPoint(BaseModel):
    """Tanggal selalu UTC dalam format ``YYYY-MM-DD``."""

    date: str
    avg_ms: int
    p95_ms: int


class TokenPoint(BaseModel):
    date: str
    input_tokens: int
    output_tokens: int


class AnalyticsSummaryResponse(BaseModel):
    """``latest_eval`` boleh ``None``; frontend menampilkan empty state."""

    latest_eval: EvalRunResponse | None = None
    latency: list[LatencyPoint] = Field(default_factory=list)
    tokens: list[TokenPoint] = Field(default_factory=list)


class QueryLogResponse(BaseModel):
    id: str
    session_id: str | None
    question: str
    response_time_ms: int
    sources_count: int
    created_at: str
    from_cache: bool
    trace_id: str | None = None


class AnalyticsLogsResponse(BaseModel):
    items: list[QueryLogResponse]
    total: int
    page: int
    page_size: int


# ----------------------------------------------------------------- health


class HealthResponse(BaseModel):
    """Status komponen yang sedang aktif.

    ``fallback`` sengaja ada di kontrak ini, bukan hanya di log server.
    Frontend menampilkan pengingat kalau ``mode`` bukan ``full``, karena indeks
    yang hilang setiap restart adalah pengalaman yang sangat berbeda, dan
    pengguna berhak tahu sebelum menemukan sendiri.
    """

    status: Literal["ok", "degraded"]
    llm: Literal["ok", "unreachable"]
    vector_store: Literal["ok", "unreachable"]
    memory: Literal["ok", "unreachable"]
    version: str
    fallback: dict[str, str | bool] = Field(default_factory=dict)


# ------------------------------------------------------------------ error


class ErrorResponse(BaseModel):
    """Bentuk error seragam. ``detail`` ditulis untuk dibaca manusia."""

    detail: str
    code: str | None = None


# --------------------------------------------------------------- mapper


def document_to_summary(document: Document) -> DocumentSummary:
    return DocumentSummary(
        id=document.id,
        filename=document.filename,
        size_bytes=document.size_bytes,
        status=document.status,
        uploaded_at=document.uploaded_at,
        page_count=document.page_count,
        chunk_count=document.chunk_count or None,
        error_message=document.error_message,
    )


def document_to_detail(document: Document, ingestion: IngestionInfo) -> DocumentDetail:
    return DocumentDetail(**document_to_summary(document).model_dump(), ingestion=ingestion)


def chunk_to_response(chunk: Chunk) -> ChunkResponse:
    return ChunkResponse(
        id=chunk.id,
        document_id=chunk.document_id,
        chunk_index=chunk.chunk_index,
        page_number=chunk.page_number,
        content=chunk.content,
        token_count=chunk.token_count,
    )


def citation_to_response(citation: Citation) -> CitationResponse:
    return CitationResponse(
        document_id=citation.document_id,
        document_name=citation.document_name,
        page_number=citation.page_number,
        chunk_index=citation.chunk_index,
        excerpt=citation.excerpt,
        score=round(citation.score, 4),
    )


def message_to_response(message: ChatMessage) -> ChatMessageResponse:
    return ChatMessageResponse(
        id=message.id,
        role=message.role.value,
        content=message.content,
        created_at=message.created_at,
        citations=[citation_to_response(item) for item in message.citations],
        not_found=message.not_found,
    )


def session_to_response(session: ChatSession) -> ChatSessionResponse:
    return ChatSessionResponse(
        id=session.id,
        title=session.title,
        created_at=session.created_at,
        last_active_at=session.last_active_at,
        message_count=session.message_count,
    )


def log_to_response(log: QueryLog) -> QueryLogResponse:
    return QueryLogResponse(
        id=log.id,
        session_id=log.session_id,
        question=log.question,
        response_time_ms=log.response_time_ms,
        sources_count=log.sources_count,
        created_at=log.created_at,
        from_cache=log.from_cache,
        trace_id=log.trace_id,
    )


__all__ = [
    "AnalyticsLogsResponse",
    "AnalyticsSummaryResponse",
    "ChatHistoryResponse",
    "ChatMessageResponse",
    "ChatQueryRequest",
    "ChatSessionResponse",
    "ChunkPage",
    "ChunkResponse",
    "CitationResponse",
    "DocumentDetail",
    "DocumentStatusResponse",
    "DocumentSummary",
    "ErrorResponse",
    "EvalRunResponse",
    "HealthResponse",
    "IngestionInfo",
    "LatencyPoint",
    "PasscodeRequest",
    "PasscodeResponse",
    "QueryLogResponse",
    "SessionRenameRequest",
    "SettingsResponse",
    "SettingsUpdate",
    "TokenPoint",
    "chunk_to_response",
    "citation_to_response",
    "document_to_detail",
    "document_to_summary",
    "log_to_response",
    "message_to_response",
    "session_to_response",
    "_utc_now",
]
