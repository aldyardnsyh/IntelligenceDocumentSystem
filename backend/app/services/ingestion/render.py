"""Render halaman PDF menjadi gambar PNG untuk pipeline vision OCR.

Text-layer PDF hasil pindai sering tidak ada atau — seperti PDF Lembaran
Negara dari BPK — ada tapi kualitasnya buruk: urutan baca kacau dan kata
terpecah. Satu-satunya sumber kebenaran yang tersisa adalah citra halamannya
sendiri. Render dilakukan dengan ``pypdfium2`` karena murni wheel Python:
tidak ada poppler atau ghostscript yang harus diinstal di Docker maupun di
Windows developer.
"""

from __future__ import annotations

import io
import logging

logger = logging.getLogger(__name__)


class RenderError(RuntimeError):
    """PDF tidak bisa dirender menjadi gambar halaman."""


def render_pdf_pages(data: bytes, scale: float) -> list[tuple[int, bytes]]:
    """Render setiap halaman PDF menjadi PNG.

    Args:
        data: Isi berkas PDF mentah.
        scale: Skala render relatif terhadap 72 DPI. 2.0 berarti 144 DPI —
            cukup untuk teks cetak, tanpa membuat body request membengkak.

    Returns:
        Daftar ``(page_number, png_bytes)`` terurut, halaman mulai dari 1.

    Raises:
        RenderError: PDF rusak atau tidak punya halaman yang bisa dirender.
    """
    try:
        import pypdfium2 as pdfium
    except ImportError as exc:  # pragma: no cover - ketergantungan wajib
        raise RenderError(
            "Pustaka pypdfium2 belum terpasang di server. "
            "Jalankan `pip install -e .` ulang di backend."
        ) from exc

    try:
        document = pdfium.PdfDocument(data)
    except Exception as exc:  # noqa: BLE001
        raise RenderError(f"PDF tidak bisa dibuka untuk dirender: {exc}") from exc

    rendered: list[tuple[int, bytes]] = []
    try:
        for index in range(len(document)):
            page_number = index + 1
            try:
                bitmap = document[index].render(scale=scale)
                image = bitmap.to_pil()
            except Exception as exc:  # noqa: BLE001
                raise RenderError(
                    f"Halaman {page_number} gagal dirender: {exc}"
                ) from exc
            buffer = io.BytesIO()
            image.save(buffer, format="PNG")
            rendered.append((page_number, buffer.getvalue()))
    finally:
        document.close()

    if not rendered:
        raise RenderError("PDF tidak punya halaman yang bisa dirender.")

    total_bytes = sum(len(payload) for _, payload in rendered)
    logger.info(
        "Render %d halaman PDF: %.1f MB gambar total (scale %.1f)",
        len(rendered),
        total_bytes / (1024 * 1024),
        scale,
    )
    return rendered
