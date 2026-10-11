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
    """Status ingestion dokumen.

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
    """Potongan teks beserta posisinya di dokumen.

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

    ``score`` adalah skor gabungan hybrid retrieval: RRF yang sudah dinormalisasi
    ke rentang 0..1. **Bukan** cosine similarity, dan tidak bisa dibandingkan
    dengan ``similarity_threshold``, ambang itu dinilai pada bukti mentah
    (``vector_score`` dan ``keyword_score``), bukan pada skor RRF. Mencampur
    keduanya adalah penyebab paling umum threshold terlihat rusak padahal tidak.
    """

    chunk: Chunk
    document_name: str
    score: float
    vector_score: float
    keyword_score: float


@dataclass(slots=True)
class Citation:
    """Satu sumber yang bisa ditelusuri.

    ``score`` di sini adalah skor gabungan hybrid retrieval (RRF yang sudah
    dinormalisasi ke 0..1), **bukan** cosine similarity. Dua angka itu tidak
    bisa dibandingkan: skor RRF selalu 1.0 untuk kandidat terbaik, sedangkan
    cosine tidak pernah sampai 1.0 kecuali teksnya identik.
    """

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
    #: Jawaban dari pengetahuan umum model, bukan dari dokumen. Disimpan
    #: supaya label "bukan dari dokumen" tetap ada saat riwayat dibuka lagi,
    #: label yang hilang setelah reload membuat jawaban lama terlihat
    #: bersumber, dan itu persis salah paham yang labelnya mencegah.
    ungrounded: bool = False


@dataclass(slots=True)
class ChatSession:
    """Sesi percakapan. Isi pesanannya disimpan terpisah di memory store.

    ``document_id`` memberi sesi ini ruang lingkup: kalau terisi, retrieval
    hanya boleh memakai dokumen itu. Sesi global (``None``) boleh memakai
    semua dokumen. Inilah yang membuat "chat privat" per dokumen mungkin tanpa
    harus menyalin dokumen atau menyetel filter di setiap request.
    """

    id: str
    title: str
    created_at: str
    last_active_at: str
    message_count: int = 0
    document_id: str | None = None


@dataclass(slots=True)
class RetrievalSettings:
    """Parameter retrieval yang bisa diubah user."""

    top_k: int
    similarity_threshold: float


@dataclass(slots=True)
class QueryLog:
    """Satu baris log query untuk dashboard analitik."""

    id: str
    session_id: str | None
    question: str
    response_time_ms: int
    sources_count: int
    created_at: str
    from_cache: bool = False
    trace_id: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)
