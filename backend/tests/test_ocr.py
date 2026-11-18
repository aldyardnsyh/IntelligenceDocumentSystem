"""Test jalur OCR vision: service OCR, keputusan mode auto, dan integrasi.

Semua test di sini berjalan tanpa jaringan: provider vision diganti stub atau
MockProvider, dan PDF yang dirender dibuat dengan reportlab. Yang diuji adalah
kontrak jalurnya — halaman terkirim sebagai gambar, hasil OCR menggantikan
text-layer, kegagalan degradasi terkontrol — bukan akurasi modelnya.
"""

from __future__ import annotations

import io

import pytest

from app.core.config import Settings
from app.models.domain import DocumentStatus
from app.providers.base import ProviderError
from app.providers.mock import MOCK_OCR_TEXT
from app.services.ingestion.ocr import OcrError, VisionOCRService, _strip_code_fences
from app.services.ingestion.parser import parse_document


def _make_pdf_with_text(text: str) -> bytes:
    """PDF satu halaman berisi teks nyata, dibuat lewat reportlab."""
    from reportlab.pdfgen import canvas

    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=(400, 200))
    pdf.drawString(20, 100, text[:200])
    pdf.showPage()
    pdf.save()
    return buffer.getvalue()


class StubVisionProvider:
    """Provider vision yang perilakunya dikontrol test."""

    def __init__(
        self,
        *,
        configured: bool = True,
        result: str = MOCK_OCR_TEXT,
        error: ProviderError | None = None,
        failures: int = 0,
    ) -> None:
        self.name = "stub-vision"
        self._configured = configured
        self._result = result
        self._error = error
        self._failures = failures
        self.calls = 0
        self.images: list[list[bytes]] = []

    def is_configured(self) -> bool:
        return self._configured

    async def complete_vision(
        self, prompt: str, images: list[bytes], system: str | None = None
    ) -> str:
        self.calls += 1
        self.images.append(images)
        if self._error is not None:
            raise self._error
        if self.calls <= self._failures:
            # retry_after_seconds=0 supaya test tidak benar-benar menunggu
            # jeda backoff — yang diuji logika percobaannya, bukan tidurnya.
            raise ProviderError(
                "rate limit", retryable=True, status_code=429, retry_after_seconds=0.0
            )
        return self._result


class TestStripCodeFences:
    def test_tanpa_fence_tidak_berubah(self) -> None:
        assert _strip_code_fences("Pasal 1\nIsi.") == "Pasal 1\nIsi."

    def test_fence_utuh_dibuang(self) -> None:
        assert _strip_code_fences("```\nPasal 1\n```") == "Pasal 1"

    def test_fence_berlabel_dibuang(self) -> None:
        assert _strip_code_fences("```text\nPasal 1\nIsi.\n```") == "Pasal 1\nIsi."


class TestVisionOCRService:
    async def test_halaman_dikirim_sebagai_gambar(self) -> None:
        provider = StubVisionProvider()
        service = VisionOCRService(Settings(), provider)
        pages = await service.ocr_pages([(1, b"gambar-halaman-1")])
        assert pages[0].text == MOCK_OCR_TEXT
        assert pages[0].page_number == 1
        assert provider.images == [[b"gambar-halaman-1"]]

    async def test_nomor_halaman_dipertahankan(self) -> None:
        provider = StubVisionProvider()
        service = VisionOCRService(Settings(), provider)
        pages = await service.ocr_pages([(3, b"a"), (4, b"b")])
        assert [page.page_number for page in pages] == [3, 4]

    async def test_retry_dengan_gagal_sementara(self) -> None:
        provider = StubVisionProvider(failures=1)
        service = VisionOCRService(Settings(), provider)
        pages = await service.ocr_pages([(1, b"a")])
        assert provider.calls == 2
        assert pages[0].text == MOCK_OCR_TEXT

    async def test_gagal_tidak_retryable_langsung_berhenti(self) -> None:
        provider = StubVisionProvider(
            error=ProviderError("kredensial salah", retryable=False, status_code=401)
        )
        service = VisionOCRService(Settings(), provider)
        with pytest.raises(OcrError, match="Halaman 2"):
            await service.ocr_pages([(2, b"a")])
        assert provider.calls == 1

    async def test_gagal_setelah_batas_percobaan(self) -> None:
        settings = Settings(ocr_max_retries=2)
        provider = StubVisionProvider(failures=99)
        service = VisionOCRService(settings, provider)
        with pytest.raises(OcrError):
            await service.ocr_pages([(1, b"a")])
        # 1 percobaan awal + 2 percobaan ulang.
        assert provider.calls == 3

    async def test_respons_kosong_dihitung_gagal(self) -> None:
        settings = Settings(ocr_max_retries=0)
        provider = StubVisionProvider(result="")
        service = VisionOCRService(settings, provider)
        with pytest.raises(OcrError, match="kosong"):
            await service.ocr_pages([(1, b"a")])


class TestKeputusanModeAuto:
    def test_pdf_teks_rusak_ditandai_perlu_ocr(self) -> None:
        # Text-layer dengan kata terpecah, pola asli Lembaran Negara BPK.
        data = _make_pdf_with_text("Undang-Undan g Tah un 2004 pen ye lenggara l.")
        settings = Settings(ingest_pdf_mode="auto")
        parsed = parse_document("perpres.pdf", data, settings)
        assert parsed.needs_ocr is True
        assert parsed.text_quality is not None and parsed.text_quality.reasons

    def test_pdf_teks_bersih_tidak_perlu_ocr(self) -> None:
        data = _make_pdf_with_text(
            "Penyelenggara wajib menyelesaikan setiap pengaduan paling lambat "
            "enam puluh hari sejak berkas pengaduan dinyatakan lengkap."
        )
        settings = Settings(ingest_pdf_mode="auto")
        parsed = parse_document("sop.pdf", data, settings)
        assert parsed.needs_ocr is False

    def test_mode_vision_selalu_perlu_ocr(self) -> None:
        data = _make_pdf_with_text("Teks bersih dan utuh tanpa kerusakan apa pun.")
        settings = Settings(ingest_pdf_mode="vision")
        parsed = parse_document("sop.pdf", data, settings)
        assert parsed.needs_ocr is True

    def test_mode_text_tidak_pernah_perlu_ocr(self) -> None:
        data = _make_pdf_with_text("Undang-Undan g Tah un 2004 pen ye lenggara l.")
        settings = Settings(ingest_pdf_mode="text")
        parsed = parse_document("perpres.pdf", data, settings)
        assert parsed.needs_ocr is False


class TestIntegrasiIngestionVision:
    """Dokumen PDF sungguhan lewat jalur vision mock sampai jadi chunk."""

    async def test_pdf_jadi_chunk_per_pasal(
        self,
        repository,
        store,
        retriever,
        embedding,
        memory,
    ) -> None:
        from app.services.ingestion.service import IngestionService

        settings = Settings(
            ingest_pdf_mode="vision",
            vision_provider="mock",
            ocr_request_delay_seconds=0,
        )
        service = IngestionService(settings, repository, store, retriever, embedding, memory)
        document = await service.register("perpres-uji.pdf", _make_pdf_with_text("Teks pindai."))
        await service.wait_pending()

        stored = repository.get_document(document.id)
        assert stored is not None and stored.status == DocumentStatus.READY
        chunks, total = repository.get_chunks(document.id, 1, 50, None)
        assert total > 0
        sections = {chunk.section for chunk in chunks}
        assert "Pasal 1" in sections
        # Isi chunk berasal dari hasil OCR mock, bukan text-layer.
        assert any("Pelayanan publik adalah" in chunk.content for chunk in chunks)

    async def test_provider_vision_tidak_siap_fallback_ke_text_layer(
        self,
        repository,
        store,
        retriever,
        embedding,
        memory,
    ) -> None:
        from app.services.ingestion.service import IngestionService

        # VISION_PROVIDER=groq tanpa API key dan mesin lokal dimatikan
        # (ocr_engine=vision): tidak ada mesin yang siap, dokumen tetap
        # terindeks dari text-layer yang ada.
        settings = Settings(
            ingest_pdf_mode="vision",
            ocr_engine="vision",
            vision_provider="groq",
            groq_api_key=None,
        )
        service = IngestionService(settings, repository, store, retriever, embedding, memory)
        teks = "Penyelenggara wajib menyelesaikan pengaduan paling lambat enam puluh hari."
        document = await service.register("sop.pdf", _make_pdf_with_text(teks))
        await service.wait_pending()

        stored = repository.get_document(document.id)
        assert stored is not None and stored.status == DocumentStatus.READY
        chunks, total = repository.get_chunks(document.id, 1, 50, None)
        assert total > 0
        assert any("enam puluh hari" in chunk.content for chunk in chunks)

    async def test_ocr_gagal_dengan_text_layer_tetap_terindeks(
        self,
        repository,
        store,
        retriever,
        embedding,
        memory,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from app.services.ingestion import service as service_module
        from app.services.ingestion.service import IngestionService

        # ocr_max_retries=0 supaya kegagalan diuji dalam satu percobaan,
        # tanpa jeda backoff sungguhan.
        settings = Settings(
            ingest_pdf_mode="vision",
            ocr_engine="vision",
            vision_provider="groq",
            groq_api_key="k",
            ocr_max_retries=0,
        )
        gagal = StubVisionProvider(
            error=ProviderError(
                "gangguan", retryable=True, status_code=500, retry_after_seconds=0.0
            )
        )
        monkeypatch.setattr(
            service_module, "build_vision_provider", lambda _settings: gagal
        )
        service = IngestionService(settings, repository, store, retriever, embedding, memory)
        teks = "Penyelenggara wajib menyelesaikan pengaduan paling lambat enam puluh hari."
        document = await service.register("sop.pdf", _make_pdf_with_text(teks))
        await service.wait_pending()

        stored = repository.get_document(document.id)
        assert stored is not None and stored.status == DocumentStatus.READY
        chunks, _ = repository.get_chunks(document.id, 1, 50, None)
        assert any("enam puluh hari" in chunk.content for chunk in chunks)

    async def test_ocr_gagal_tanpa_text_layer_gagal_terdokumentasi(
        self,
        repository,
        store,
        retriever,
        embedding,
        memory,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from app.services.ingestion import service as service_module
        from app.services.ingestion.service import IngestionService

        settings = Settings(ingest_pdf_mode="vision", vision_provider="groq", groq_api_key="k")
        gagal = StubVisionProvider(
            error=ProviderError("kredensial salah", retryable=False, status_code=401)
        )
        monkeypatch.setattr(
            service_module, "build_vision_provider", lambda _settings: gagal
        )
        service = IngestionService(settings, repository, store, retriever, embedding, memory)
        # PDF halaman kosong: tidak ada text-layer untuk kembali.
        document = await service.register("scan.pdf", _make_pdf_blank())
        await service.wait_pending()

        stored = repository.get_document(document.id)
        assert stored is not None and stored.status == DocumentStatus.FAILED
        assert stored.error_message is not None


def _make_pdf_blank() -> bytes:
    """PDF satu halaman tanpa teks — simulasi hasil pindai murni."""
    from pypdf import PdfWriter

    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()
