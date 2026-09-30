"""Model data internal (Pydantic).

Pemisahan penting: model di sini adalah bentuk *internal* yang dipakai
service-service. Bentuk *eksternal* yang dilihat frontend didefinisikan di
``app.models.schemas`` dan sengaja terpisah, supaya perubahan internal tidak
langsung mengubah kontrak API.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class DocumentStatus(StrEnum):
    """Status ingestion dokumen (FR-1.3).

    ``StrEnum`` (bukan ``str, Enum``) karena proyek mensyaratkan Python 3.11.
    Bedanya bukan cuma gula sintaks: dengan ``StrEnum``,
    ``f"{status}"`` menghasilkan ``"ready"``, sedangkan dengan ``str, Enum``
    hasilnya ``"DocumentStatus.READY"``. Itu perbedaan yang mudah salah
    diam-diam di respons API.
    """

    UPLOADING = "uploading"
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"


class MessageRole(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"


@dataclass(slots=True)
class Document:
    """Metadata dokumen."""

    id: str
    filename: str
    size_bytes: int
    status: DocumentStatus
    uploaded_at: str
    page_count: int | None = None
    chunk_count: int = 0
    error_message: str | None = None


@dataclass(slots=True)
class Chunk:
    """Potongan teks beserta posisinya di dokumen (PRD 8.3).

    ``document_name`` diisi ketika chunk dibaca kembali dari penyimpanan.
    Saat chunk baru dibuat dari parsing, kolom ini masih ``None`` karena nama
    dokumen ada di level dokumen, bukan chunk; yang baru dibutuhkan saat
    membangun ulang indeks retrieval setelah restart.
    """

    id: str
    document_id: str
    chunk_index: int
    content: str
    page_number: int | None = None
    token_count: int | None = None
    char_start: int = 0
    char_end: int = 0
    document_name: str | None = None


@dataclass(slots=True)
class RetrievedChunk:
    """Hasil retrieval, siap dikirim ke generator.

    ``score`` adalah cosine similarity gabungan dari vector dan BM25, sudah
    dinormalisasi ke rentang 0..1 supaya bisa dibandingkan dengan
    ``similarity_threshold``.
    """

    chunk: Chunk
    document_name: str
    score: float
    vector_score: float
    keyword_score: float


@dataclass(slots=True)
class Citation:
    """Satu sumber yang bisa ditelusuri (FR-2.2)."""

    document_id: str
    document_name: str
    page_number: int | None
    chunk_index: int
    excerpt: str
    score: float


@dataclass(slots=True)
class ChatMessage:
    """Satu pesan dalam percakapan."""

    id: str
    role: MessageRole
    content: str
    created_at: str
    citations: list[Citation] = field(default_factory=list)
    not_found: bool = False


@dataclass(slots=True)
class ChatSession:
    """Sesi percakapan. Isi pesanannya disimpan terpisah di memory store."""

    id: str
    title: str
    created_at: str
    last_active_at: str
    message_count: int = 0


@dataclass(slots=True)
class RetrievalSettings:
    """Parameter retrieval yang bisa diubah user (FR-6.1)."""

    top_k: int
    similarity_threshold: float


@dataclass(slots=True)
class QueryLog:
    """Satu baris log query untuk dashboard analitik (FR-7.2)."""

    id: str
    session_id: str | None
    question: str
    response_time_ms: int
    sources_count: int
    created_at: str
    from_cache: bool = False
    trace_id: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)
