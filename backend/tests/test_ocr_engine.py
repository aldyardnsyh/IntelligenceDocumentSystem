"""Test rekonstruksi urutan baca OCR dan pipeline hybrid.

Layout dua kolom adalah penyebab utama urutan baca kacau pada Lembaran Negara.
Rekonstruksi diuji dengan kotak sintetis: kolom kiri utuh sebelum kanan,
header pembentang diletakkan di depan, dan layout satu kolom tetap terbaca
atas ke bawah. Pipeline hybrid diuji dengan mesin lokal palsu, tanpa model
sungguhan.
"""

from __future__ import annotations

import asyncio

import pytest

from app.core.config import Settings
from app.services.ingestion.ocr import HybridOcrService
from app.services.ingestion.ocr_engine import (
    OcrLine,
    PaddleOcrEngine,
    find_gap_bands,
    lines_to_page_text,
    page_confidence,
    reconstruct_reading_order,
)


def _line(
    text: str, x: float, y: float, w: float = 200.0, h: float = 20.0, conf: float = 0.95
) -> OcrLine:
    return OcrLine(text=text, confidence=conf, x=x, y=y, width=w, height=h)


class TestReadingOrder:
    def test_satu_kolom_terbaca_atas_ke_bawah(self) -> None:
        lines = [
            _line("ketiga", 10, 400),
            _line("pertama", 10, 100),
            _line("kedua", 10, 250),
        ]
        ordered = reconstruct_reading_order(lines)
        assert [line.text for line in ordered] == ["pertama", "kedua", "ketiga"]

    def test_dua_kolom_kiri_utuh_dulu(self) -> None:
        # Halaman 400 lebar; kolom kiri x=10..180, kolom kanan x=230..400.
        # Gutter tengah (180..230) harus cukup lebar untuk terdeteksi.
        lines = [
            _line("kanan-atas", 230, 100, w=170),
            _line("kiri-bawah", 10, 300, w=170),
            _line("kiri-atas", 10, 100, w=170),
            _line("kanan-bawah", 230, 300, w=170),
        ]
        ordered = reconstruct_reading_order(lines)
        assert [line.text for line in ordered] == [
            "kiri-atas",
            "kiri-bawah",
            "kanan-atas",
            "kanan-bawah",
        ]

    def test_header_pembentang_di_awal(self) -> None:
        # Header halaman membentang melewati gutter; ia harus dibaca pertama,
        # bukan tercampur ke kolom kiri.
        lines = [
            _line("kiri-atas", 10, 100),
            _line("kanan-atas", 210, 100),
            _line("JUDUL HALAMAN MEMBENTANG", 5, 10, w=390),
        ]
        ordered = reconstruct_reading_order(lines)
        assert ordered[0].text.startswith("JUDUL HALAMAN")

    def test_kosong_aman(self) -> None:
        assert reconstruct_reading_order([]) == []


class TestLinesToPageText:
    def test_jeda_vertikal_jadi_paragraf(self) -> None:
        lines = [
            _line("baris pertama", 10, 0, h=20),
            _line("baris kedua", 10, 22, h=20),
            # Jeda 100 piksel, jauh di atas tinggi baris: paragraf baru.
            _line("paragraf baru", 10, 122, h=20),
        ]
        text = lines_to_page_text(lines)
        assert "baris pertama\nbaris kedua" in text
        assert "\n\n" in text

    def test_kosong_kosong(self) -> None:
        assert lines_to_page_text([]) == ""


class TestPageConfidence:
    def test_rata_rata(self) -> None:
        lines = [_line("a", 0, 0, conf=0.9), _line("b", 0, 5, conf=0.7)]
        assert page_confidence(lines) == pytest.approx(0.8)

    def test_halaman_kosong_nol(self) -> None:
        assert page_confidence([]) == 0.0


class _FakePaddleEngine:
    """Mesin lokal palsu dengan perilaku yang dikontrol test."""

    def __init__(self, lines: list[OcrLine]) -> None:
        self._lines = lines
        self.calls = 0

    def recognize_page(self, image_bytes: bytes) -> list[OcrLine]:
        self.calls += 1
        return self._lines

    def recover_missing_lines(
        self, image_bytes: bytes, detected: list[OcrLine], *, zoom: float = 2.0
    ) -> list[OcrLine]:
        return []


class _StubVision:
    """Pengganti VisionOCRService yang menghitung pemanggilan."""

    def __init__(self) -> None:
        self.calls = 0

    async def ocr_pages(self, rendered):  # pragma: no cover - tidak dipakai di sini
        raise AssertionError("ocr_pages penuh tidak boleh dipakai pipeline hybrid")

    async def transcribe_page(self, page_number: int, image: bytes) -> str:
        self.calls += 1
        return f"teks vision halaman {page_number}"


def _make_hybrid(
    lines: list[OcrLine], *, engine: str = "auto"
) -> tuple[HybridOcrService, _StubVision]:
    settings = Settings(ocr_engine=engine, ocr_vlm_rescue_confidence=0.55)
    service = HybridOcrService.__new__(HybridOcrService)
    service._settings = settings  # noqa: SLF001
    service._paddle = _FakePaddleEngine(lines)  # noqa: SLF001
    vision = _StubVision()
    service._vision = vision  # type: ignore[assignment]  # noqa: SLF001
    service._rescue_enabled = engine == "auto"  # noqa: SLF001
    return service, vision


class TestHybridPipeline:
    def test_halaman_percaya_diri_tidak_ke_vision(self) -> None:
        lines = [_line(f"baris {i}", 10, i * 24) for i in range(8)]
        service, vision = _make_hybrid(lines)
        pages = asyncio.run(service.ocr_pages([(1, b"png")]))
        assert pages[0].text.startswith("baris 0")
        assert vision.calls == 0

    def test_halaman_confidence_rendah_dieskalasi(self) -> None:
        lines = [_line(f"baris {i}", 10, i * 24, conf=0.3) for i in range(8)]
        service, vision = _make_hybrid(lines)
        pages = asyncio.run(service.ocr_pages([(3, b"png")]))
        assert pages[0].text == "teks vision halaman 3"
        assert vision.calls == 1

    def test_mode_paddle_tidak_pernah_ke_vision(self) -> None:
        lines = [_line(f"baris {i}", 10, i * 24, conf=0.2) for i in range(8)]
        service, vision = _make_hybrid(lines, engine="paddle")
        pages = asyncio.run(service.ocr_pages([(1, b"png")]))
        assert "baris" in pages[0].text
        assert vision.calls == 0


class TestGapBands:
    """Deteksi celah vertikal: baris hilang tertutup cap tinta."""

    def test_gap_besar_terdeteksi_per_kolom(self) -> None:
        # Kolom kiri: 3 baris rapat, lalu celah 100px (baris hilang), lanjut.
        kiri = [
            _line("a1", 10, 0, w=170),
            _line("a2", 10, 24, w=170),
            # gap 100px di sini (y 44 -> 144)
            _line("a3", 10, 144, w=170),
        ]
        kanan = [
            _line("b1", 230, 0, w=170),
            _line("b2", 230, 24, w=170),
        ]
        bands = find_gap_bands(kiri + kanan, page_width=400)
        assert len(bands) == 1
        x0, y0, x1, y1 = bands[0]
        # Band kini diberi padding vertikal: pad = max(6.0, 0.8 * median
        # tinggi baris 20) = 16, sehingga y0 = 44 + 2 - 16 = 30 dan
        # y1 = 144 - 2 + 16 = 158. Band boleh menimpa baris tetangga.
        assert y0 == pytest.approx(30, abs=3)
        assert y1 == pytest.approx(158, abs=3)
        # Band hanya mencakup kolom kiri, bukan selebar halaman.
        assert x1 <= 185

    def test_gap_normal_tidak_terdeteksi(self) -> None:
        lines = [
            _line("a1", 10, 0),
            _line("a2", 10, 24),
            _line("a3", 10, 48),
        ]
        assert find_gap_bands(lines, page_width=400) == []

    def test_tanpa_baris_aman(self) -> None:
        assert find_gap_bands([], page_width=400) == []


class _StubCropEngine(PaddleOcrEngine):
    """Engine lokal palsu: model tidak dimuat, recognize_page dikembalikan tetap.

    Koordinat fragmen berada di ruang crop yang sudah diperbesar 2x — sama
    seperti keluaran asli mesin, sebelum dipetakan balik ke koordinat halaman.
    """

    def __init__(self, fragments: list[OcrLine]) -> None:
        super().__init__()
        self._fragments = fragments

    def recognize_page(self, image_bytes: bytes) -> list[OcrLine]:
        return list(self._fragments)


def _page_png(width: int = 400, height: int = 200) -> bytes:
    """Halaman putih polos; recover_missing_lines hanya butuh gambar untuk crop."""
    import io

    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (width, height), "white").save(buffer, format="PNG")
    return buffer.getvalue()


class TestRecoverMissingLines:
    """Pemulihan baris hilang: fragmen satu baris fisik digabung jadi satu.

    Tanpa penggabungan, baris yang dipulihkan kembali sebagai pecahan-pecahan
    ("lambat", "60", "(enam", ...) — dan pecahan angka berdiri sendiri seperti
    "60" berpola sama dengan nomor halaman sehingga terbuang saat pembersihan.
    """

    # Baris sintetis dengan satu celah 120px (baris hilang) di tengah:
    # pitch 24, min_gap 38.4, band = (10, 44+2-16, 180, 144-2+16) = 30..158.
    _detected = [
        _line("a1", 10, 0, w=170),
        _line("a2", 10, 24, w=170),
        _line("a3", 10, 144, w=170),
        _line("a4", 10, 168, w=170),
    ]

    def test_fragmen_satu_baris_tergabung(self) -> None:
        # Tiga fragmen di ruang crop 2x; dipetakan balik ke halaman menjadi
        # y=50..67 (di dalam celah 46..142, tidak menimpa baris terdeteksi).
        fragments = [
            _line("lambat", 20, 40, w=120, h=30),
            _line("60", 160, 40, w=40, h=30),
            _line("puluh", 220, 44, w=80, h=30),
        ]
        engine = _StubCropEngine(fragments)
        recovered = engine.recover_missing_lines(_page_png(), list(self._detected))
        assert len(recovered) == 1
        assert recovered[0].text == "lambat 60 puluh"
        assert recovered[0].x == pytest.approx(20, abs=1)
        assert recovered[0].y == pytest.approx(50, abs=1)

    def test_baris_visual_berbeda_tidak_tergabung(self) -> None:
        # Dua fragmen dengan tengah vertikal terpisah jauh: tetap dua baris.
        fragments = [
            _line("atas", 20, 40, w=120, h=30),
            _line("bawah", 20, 110, w=120, h=30),
        ]
        engine = _StubCropEngine(fragments)
        recovered = engine.recover_missing_lines(_page_png(), list(self._detected))
        assert [line.text for line in recovered] == ["atas", "bawah"]
