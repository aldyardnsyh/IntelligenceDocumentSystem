"""OCR halaman PDF hasil pindai: PP-OCR lokal utama, model vision untuk halaman sulit.

Alurnya: halaman dirender menjadi gambar (``render.py``), lalu setiap gambar
diekstraksi. Mesin lokal (PP-OCR via ``ocr_engine.py``) menangani mayoritas
halaman tanpa biaya, dan hanya halaman yang confidence-nya rendah dikirim ke
model vision. Hasilnya menggantikan text-layer yang kosong atau rusak — dan
karena sumbernya citra halaman langsung, urutan baca logis dan kata yang utuh
kembali lagi, hal yang tidak mungkin dipulihkan dari text-layer yang sudah
kacau sejak awal.

Panggilan ke model vision berjalan sekuensial dengan jeda antar halaman, bukan
paralel: free tier provider vision membatasi token per menit, dan satu
unggahan bisa mencakup belasan halaman yang masing-masing beribu token. Jeda
kecil per halaman jauh lebih murah daripada 429 beruntun yang menggagalkan
seluruh ingestion.
"""

from __future__ import annotations

import asyncio
import logging

from app.core.config import Settings
from app.providers.base import LLMProvider, ProviderError
from app.services.ingestion.cleanup import clean_page_text
from app.services.ingestion.ocr_engine import (
    PaddleOcrEngine,
    lines_to_page_text,
    paddle_available,
    page_confidence,
    reconstruct_reading_order,
)
from app.services.ingestion.parser import ParsedPage

logger = logging.getLogger(__name__)

#: Halaman dengan teks lebih pendek dari ini dianggap gagal oleh mesin lokal
#: (halaman kosong, atau PP-OCR tidak menangkap apa pun) dan layak diselamatkan.
MIN_RESCUE_CHARS = 40


class OcrError(RuntimeError):
    """OCR gagal. Pesannya menyebut halaman penyebab supaya bisa didiagnosis."""


#: Konteks peran. Instruksi teknis ada di prompt user supaya provider yang
#: mengabaikan system prompt tetap mendapat aturan yang sama.
OCR_SYSTEM_PROMPT = (
    "Anda adalah mesin transkripsi OCR untuk dokumen hukum Indonesia hasil pindai. "
    "Keluarkan hanya teks halaman, tanpa penjelasan apa pun."
)

OCR_USER_PROMPT = """Transkripsikan seluruh teks pada gambar halaman dokumen hukum Indonesia ini.

Aturan:
1. Tuliskan teks apa adanya mengikuti urutan baca logis dokumen; untuk tata
letak dua kolom atau bertingkat, susun agar kalimat tersambung utuh.
2. Pertahankan struktur: "BAB" dengan angka Romawi dan judulnya, "Bagian"
beserta judulnya, "Pasal" dengan nomornya, ayat "(N)", dan butir "a." / "1.".
3. Gabungkan kata yang terpotong pindah baris tanpa mengubah ejaan; ejaan asli
dipertahankan termasuk yang tampak salah ketik.
4. Abaikan penanda halaman di kaki halaman (nomor halaman dan cap
"PRESIDEN REPUBLIK INDONESIA").
5. Jangan menambahkan komentar, ringkasan, atau format Markdown. Keluarkan
hanya teks halaman."""

#: Batas jeda tunggu Retry-After, supaya server yang salah mengirim nilai
#: besar tidak menahan ingestion selamanya.
_MAX_RETRY_WAIT_SECONDS = 30.0


def _strip_code_fences(text: str) -> str:
    """Buang pembungkus ``` bila model mengabaikan larangan Markdown."""
    stripped = text.strip()
    if not stripped.startswith("```"):
        return stripped
    lines = stripped.split("\n")
    # Baris fence pembuka (``` atau ```text) dan penutup (```) dibuang;
    # isinya dipertahankan apa adanya.
    lines = lines[1:]
    while lines and not lines[-1].strip():
        lines.pop()
    if lines and lines[-1].strip().startswith("```"):
        lines = lines[:-1]
    return "\n".join(lines).strip()


class VisionOCRService:
    """Transkripsi halaman PDF lewat provider vision yang diberikan."""

    def __init__(self, settings: Settings, provider: LLMProvider) -> None:
        self._settings = settings
        self._provider = provider

    async def ocr_pages(
        self, rendered: list[tuple[int, bytes]]
    ) -> list[ParsedPage]:
        """Transkripsi setiap halaman yang sudah dirender, sekuensial.

        Returns:
            Daftar ``ParsedPage`` dengan nomor halaman aslinya, terurut.

        Raises:
            OcrError: Halaman pertama yang gagal setelah seluruh percobaan.
                Gagal dihentikan di halaman pertama, bukan dilanjutkan,
                karena hasil parsial membuat dokumen "siap" padahal
                sebagian isinya tidak pernah terindeks.
        """
        pages: list[ParsedPage] = []
        for index, (page_number, image) in enumerate(rendered):
            text = await self.transcribe_page(page_number, image)
            pages.append(ParsedPage(text=text, page_number=page_number))
            logger.info(
                "OCR halaman %d selesai: %d karakter", page_number, len(text)
            )
            if index < len(rendered) - 1 and self._settings.ocr_request_delay_seconds > 0:
                await asyncio.sleep(self._settings.ocr_request_delay_seconds)
        return pages

    async def transcribe_page(self, page_number: int, image: bytes) -> str:
        """Transkripsi satu halaman lewat model vision, dengan percobaan ulang.

        Rate limit provider bersifat sementara dan biasanya disertai
        ``Retry-After``; menunggu persis sebanyak itu lebih tepat daripada
        backoff buta. Error yang tidak retryable (kredensial salah, model
        tidak ada) langsung berhenti — mencoba lagi hanya menambah lambat.

        Publik karena pipeline hybrid (``HybridOcrService``) memanggilnya
        per halaman untuk menyelamatkan halaman yang confidence PP-OCR-nya
        rendah, bukan hanya seluruh dokumen sekaligus.
        """
        attempts = max(0, self._settings.ocr_max_retries) + 1
        last_error: Exception | None = None

        for attempt in range(attempts):
            try:
                raw = await self._provider.complete_vision(
                    OCR_USER_PROMPT, [image], system=OCR_SYSTEM_PROMPT
                )
            except ProviderError as exc:
                last_error = exc
                if not exc.retryable or attempt >= attempts - 1:
                    break
                wait = exc.retry_after_seconds or float(2 * (attempt + 1))
                await asyncio.sleep(min(wait, _MAX_RETRY_WAIT_SECONDS))
                continue

            text = _strip_code_fences(raw)
            if text:
                return text
            # Respons kosong dihitung gagal juga: halaman tanpa teks jauh
            # lebih mungkin tanda model gagal daripada halaman yang memang
            # kosong.
            last_error = OcrError("model mengembalikan teks kosong")
            if attempt < attempts - 1:
                await asyncio.sleep(float(2 * (attempt + 1)))

        raise OcrError(f"Halaman {page_number} gagal di-OCR: {last_error}")


class HybridOcrService:
    """Orkestrasi mesin OCR: PP-OCR lokal utama, model vision untuk halaman sulit.

    PP-OCR gratis, cepat, dan memulihkan urutan dua kolom dari bounding box.
    Kelemahannya ia jujur: confidence per baris dikembalikan apa adanya, dan
    halaman pindai yang buruk (noda, miring) menghasilkan confidence rendah.
    Justru sinyal itulah yang dipakai untuk mengirim **hanya halaman bermasalah**
    ke model vision, bukan seluruh dokumen — biaya API turun drastis tanpa
    menurunkan kualitas halaman yang benar-benar sulit.
    """

    def __init__(
        self,
        settings: Settings,
        vision_provider: LLMProvider | None = None,
    ) -> None:
        self._settings = settings
        mode = settings.ocr_engine
        self._paddle: PaddleOcrEngine | None = None
        if mode in ("auto", "paddle") and paddle_available():
            self._paddle = PaddleOcrEngine()
        self._vision: VisionOCRService | None = (
            VisionOCRService(settings, vision_provider)
            if vision_provider is not None
            else None
        )
        # Rescue hanya bermakna di mode auto: mode paddle sengaja menolak API,
        # mode vision memakai VLM untuk semua halaman.
        self._rescue_enabled = mode == "auto" and self._vision is not None

    async def ocr_pages(
        self, rendered: list[tuple[int, bytes]]
    ) -> list[ParsedPage]:
        """Ekstraksi setiap halaman sesuai konfigurasi mesin.

        Raises:
            OcrError: Halaman gagal di semua mesin yang tersedia.
        """
        if self._paddle is None and self._vision is None:
            raise OcrError(
                "Tidak ada mesin OCR yang tersedia: paket rapidocr-onnxruntime "
                "belum terpasang dan provider vision tidak siap."
            )

        pages: list[ParsedPage] = []
        rescue_count = 0
        paddle_count = 0
        vision_count = 0
        for index, (page_number, image) in enumerate(rendered):
            text, source = await self._extract_page(page_number, image)
            pages.append(ParsedPage(text=text, page_number=page_number))
            if source == "paddle":
                paddle_count += 1
            elif source == "vision":
                vision_count += 1
            else:
                rescue_count += 1
            logger.info(
                "OCR halaman %d selesai via %s: %d karakter",
                page_number,
                source,
                len(text),
            )
            # Jeda hanya berlaku setelah panggilan API (vision/rescue). Halaman
            # yang selesai sepenuhnya lokal tidak perlu jeda.
            if (
                source != "paddle"
                and index < len(rendered) - 1
                and self._settings.ocr_request_delay_seconds > 0
            ):
                await asyncio.sleep(self._settings.ocr_request_delay_seconds)

        if paddle_count or rescue_count or vision_count:
            logger.info(
                "OCR selesai: %d halaman lokal, %d diselamatkan vision, "
                "%d langsung vision",
                paddle_count,
                rescue_count,
                vision_count,
            )
        return pages

    async def _extract_page(
        self, page_number: int, image: bytes
    ) -> tuple[str, str]:
        """Ekstraksi satu halaman; kembalikan (teks, sumber hasil)."""
        if self._paddle is None:
            assert self._vision is not None
            text = clean_page_text(
                await self._vision.transcribe_page(page_number, image)
            )
            return text, "vision"

        lines = await asyncio.to_thread(self._paddle.recognize_page, image)
        if self._settings.ocr_gap_rescan_enabled:
            # Pass kedua: baris yang tertutup cap tinta sering lolos dari
            # detektor; celah antar baris di-crop dan dibaca ulang dengan zoom.
            extra = await asyncio.to_thread(
                self._paddle.recover_missing_lines, image, lines
            )
            if extra:
                logger.info(
                    "OCR halaman %d: %d baris dipulihkan via gap re-scan",
                    page_number,
                    len(extra),
                )
                lines = lines + extra
        ordered = reconstruct_reading_order(lines)
        # PP-OCR mentranskripsi cap kaki halaman juga ("PRESIDEN REPUBLIK
        # INDONESIA", nomor halaman); pembersih yang sama dengan jalur
        # text-layer membuangnya sebelum teks masuk ke chunk.
        text = clean_page_text(lines_to_page_text(ordered))
        confidence = page_confidence(lines)

        needs_rescue = (
            confidence < self._settings.ocr_vlm_rescue_confidence
            or len(text) < MIN_RESCUE_CHARS
        )
        if not needs_rescue or not self._rescue_enabled:
            return text, "paddle"

        try:
            text = await self._vision.transcribe_page(page_number, image)
        except OcrError as exc:
            # Rescue gagal bukan alasan menggagalkan halaman: teks PP-OCR yang
            # kurang percaya diri tetap jauh lebih berguna daripada halaman
            # yang tidak terindeks sama sekali.
            logger.warning(
                "Rescue vision untuk halaman %d gagal (%s); memakai hasil "
                "PP-OCR apa adanya.",
                page_number,
                exc,
            )
            return text, "paddle"
        return text, "vision-rescue"
