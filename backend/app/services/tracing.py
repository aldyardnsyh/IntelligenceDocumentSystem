"""Tracing observabilitas dengan Langfuse.

Modul ini menjawab: "setelah jawaban keluar, bisakah kita melihat kembali
langkah apa yang diambil sistem untuk sampai ke sana?" Tanpa tracing, debugging
kualitas RAG hanya bisa lewat log teks, tidak ada yang mencatat prompt
lengkap, konteks yang dipakai, dan provider mana yang akhirnya menjawab.

Desainnya defensif berlapis:

1. **Opsional penuh.** Kalau `langfuse` tidak terpasang atau
   `TRACING_ENABLED=0`, semua fungsi di sini menjadi no-op yang mengembalikan
   `None`. Kode pemanggil tidak perlu `if` di setiap baris, cukup teruskan
   hasilnya (yang mungkin `None`) ke log. Jejak yang mati tidak boleh
   mematikan jawaban.
2. **Sinkron, di thread.** Langfuse SDK melakukan I/O jaringan. Semua
   pemanggilan dibungkus `asyncio.to_thread` oleh pemanggil, bukan di sini,
   supaya event loop tidak terblokir saat Langfuse lambat.
3. **Gagal diam-diam tapi tercatat.** Kalau Langfuse down, query tetap jalan
   dan hanya kehilangan jejaknya. Error-nya masuk log server, bukan ke
   pengguna, bukan juga ditelan tanpa jejak.
"""

from __future__ import annotations

import hashlib
import logging
import os
from dataclasses import dataclass, field
from typing import Any

from app.core.config import Settings

logger = logging.getLogger(__name__)

#: Panjang cuplikan yang dikirim. Kosong secara bawaan: cuplikan pertanyaan
#: dan jawaban tetap keluar dari mesin, hanya dipotong saja.
#: Nyalakan hanya kalau ini memang Langfuse milik sendiri.
_PREVIEW_CHARS = int(os.environ.get("TRACING_INCLUDE_PREVIEW", "0") or 0)


def _redact(text: str) -> str:
    """Kirim bentuk teks, bukan isinya.

    Pertanyaan dan jawaban bisa memuat data dokumen pengguna. Yang dibutuhkan
    untuk debugging adalah "seperti apa pertanyaannya" dan "seberapa panjang
    jawabannya", bukan isi lengkapnya.
    """
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]
    if _PREVIEW_CHARS <= 0:
        return f"[{len(text)} chars sha256:{digest}]"
    preview = " ".join(text.split())[:_PREVIEW_CHARS]
    return f"[{len(text)} chars sha256:{digest}] {preview}"


@dataclass(slots=True)
class TraceContext:
    """Jejak satu query, dari retrieval sampai jawaban selesai.

    `trace_id` yang disimpan ke `QueryLog` adalah ID yang sama dengan yang
    ada di dashboard Langfuse, sehingga kolom Trace di /analytics bisa
    menaut langsung ke sana.
    """

    trace_id: str | None = None
    spans: dict[str, Any] = field(default_factory=dict)


class Tracer:
    """Pembungkus tipis di atas Langfuse SDK.

    Dibuat sekali di `init_services` dan diteruskan ke `RagService`. Kalau
    tracing mati, instansinya tetap ada tapi semua method mengembalikan
    `None`, pemanggil tidak perlu tahu bedanya.
    """

    def __init__(self, settings: Settings) -> None:
        self._enabled = bool(
            settings.tracing_enabled
            and settings.langfuse_public_key
            and settings.langfuse_secret_key
        )
        self._client: Any = None
        if self._enabled:
            try:
                from langfuse import Langfuse  # noqa: PLC0415

                self._client = Langfuse(
                    public_key=settings.langfuse_public_key,
                    secret_key=settings.langfuse_secret_key,
                    host=settings.langfuse_host,
                )
            except Exception as exc:  # noqa: BLE001
                # SDK tidak terpasang atau kredensial salah. Tracing mati,
                # aplikasi tetap jalan. Ini dicatat sebagai warning, bukan
                # error, karena dari sudut pandang pengguna tidak ada yang
                # rusak.
                logger.warning("Langfuse tidak bisa dipakai (%s). Tracing dimatikan.", exc)
                self._enabled = False

    @property
    def enabled(self) -> bool:
        return self._enabled

    def start_trace(
        self,
        *,
        question: str,
        session_id: str | None,
        metadata: dict[str, Any] | None = None,
    ) -> TraceContext:
        """Mulai jejak baru untuk satu query. Tidak pernah melempar."""
        context = TraceContext()
        if not self._enabled or self._client is None:
            return context
        try:
            trace = self._client.trace(
                name="rag-query",
                # Isi pertanyaan dan jawaban bisa memuat data dokumen pengguna,
                # dan Langfuse adalah layanan pihak ketiga. Yang dikirim hanya
                # bentuknya (panjang + hash). Isi teks hanya ikut kalau
                # `TRACING_INCLUDE_PREVIEW` dinyalakan secara eksplisit,
                # itu keputusan sadar, bukan default.
                input=_redact(question),
                session_id=session_id,
                metadata=metadata or {},
            )
            context.trace_id = trace.id
            context.spans["trace"] = trace
        except Exception as exc:  # noqa: BLE001
            logger.warning("Gagal memulai trace Langfuse: %s", exc)
        return context

    def end_trace(
        self,
        context: TraceContext,
        *,
        answer: str,
        citations: int,
        provider_name: str | None,
        from_cache: bool,
        elapsed_ms: int,
    ) -> None:
        """Tutup jejak dengan hasil akhir. Tidak pernah melempar."""
        trace = context.spans.get("trace")
        if trace is None:
            return
        try:
            trace.update(
                output=_redact(answer[:4000]),
                metadata={
                    "citations": citations,
                    "provider": provider_name,
                    "from_cache": from_cache,
                    "elapsed_ms": elapsed_ms,
                },
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Gagal menutup trace Langfuse: %s", exc)

    def span_retrieval(
        self,
        context: TraceContext,
        *,
        chunks: list[Any],
        threshold: float,
    ) -> None:
        """Catat hasil retrieval sebagai span anak. Tidak pernah melempar."""
        trace = context.spans.get("trace")
        if trace is None:
            return
        try:
            trace.span(
                name="retrieval",
                input={"threshold": threshold},
                output={
                    "chunks": [
                        {
                            "document": getattr(c, "document_name", "?"),
                            "chunk_index": getattr(c.chunk, "chunk_index", -1),
                            "score": round(getattr(c, "score", 0.0), 4),
                        }
                        for c in chunks[:10]
                    ],
                    "count": len(chunks),
                },
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Gagal mencatat span retrieval: %s", exc)

    def flush(self) -> None:
        """Kirim antrean yang tertunda. Dipanggil saat shutdown."""
        if self._client is None:
            return
        try:
            self._client.flush()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Gagal flush Langfuse: %s", exc)
