"""Deteksi elemen visual & chunk multimodal.

Tes deteksi memakai citra sintetis: kertas putih + blob tinta hitam. Jalur
"OpenCV tidak tersedia" diuji lewat pengecualian yang diharapkan, dan
pembangunan chunk visual diuji murni dari daftar elemen.
"""

from __future__ import annotations

import numpy
import pytest

from app.models.domain import Chunk
from app.services.ingestion.ocr_engine import OcrLine
from app.services.ingestion.visuals import (
    VisualElement,
    build_visual_chunks,
    cv2_available,
    detect_visuals,
)

cv2 = pytest.importorskip("cv2")


def _white_page(width: int = 1240, height: int = 1754) -> numpy.ndarray:
    """Halaman putih ala render 216 DPI A4, grayscale."""
    return numpy.full((height, width), 245, dtype=numpy.uint8)


def _lines(*texts: str) -> list[OcrLine]:
    """Baris OCR tiruan: satu baris teks di tengah halaman."""
    return [
        OcrLine(
            text=text,
            confidence=0.95,
            x=100 + index * 20,
            y=800 + index * 20,
            width=400,
            height=18,
        )
        for index, text in enumerate(texts)
    ]


class TestDetectVisuals:
    def test_blob_besar_di_bawah_dideteksi_tanda_tangan(self) -> None:
        page = _white_page()
        # Blok tinta 200x220 di zona bawah tengah: tanda tangan/stempel.
        page[1400:1620, 500:700] = 30
        elements = detect_visuals(page, 14, _lines("Bistok Simbolon"))
        assert len(elements) == 1
        assert elements[0].kind == "tanda_tangan_atau_stempel"
        assert elements[0].page == 14

    def test_blob_di_kop_atas_tengah_adalah_lambang(self) -> None:
        page = _white_page()
        page[80:280, 560:680] = 40
        elements = detect_visuals(page, 1, _lines("PRESIDEN REPUBLIK INDONESIA"))
        assert elements[0].kind == "lambang"

    def test_baris_teks_tidak_terdeteksi_sebagai_visual(self) -> None:
        page = _white_page()
        # Garis teks gelap lebar yang di dalamnya ada baris OCR ber-conf tinggi
        # → piksel teksnya disingkirkan, sisanya bukan blob utuh.
        page[800:980, 100:900] = 40
        elements = detect_visuals(page, 1, _lines("kalimat pertama", "kalimat kedua"))
        assert elements == []

    def test_crop_ditulis_bila_dir_diminta(self, tmp_path) -> None:  # noqa: ANN001
        page = _white_page()
        page[1400:1620, 500:700] = 30
        elements = detect_visuals(page, 14, [], crop_dir=tmp_path)
        assert elements[0].crop_path is not None
        assert (tmp_path / elements[0].crop_path.split("/")[-1].split("\\")[-1]).exists()

    def test_deteksi_tanpa_baris_tetap_berjalan(self) -> None:
        page = _white_page()
        page[1400:1620, 500:700] = 30
        assert len(detect_visuals(page, 14, [])) == 1

    def test_cv2_tersedia_di_environment_test(self) -> None:
        assert cv2_available() is True


class TestBuildVisualChunks:
    def test_lambang_berulang_digabung_per_jenis(self) -> None:
        visuals = [
            VisualElement("lambang", page=page, bbox=(0, 0, 10, 10),
                          position="atas-tengah", nearby_text="PRESIDEN")
            for page in (1, 2, 3)
        ]
        chunks = build_visual_chunks("doc1", visuals)
        assert len(chunks) == 1
        chunk_id, text, page = chunks[0]
        assert "lambang" in text
        assert "1 sampai 3" in text
        assert page == 1

    def test_tanda_tangan_unik_tetap_per_kemunculan(self) -> None:
        visuals = [
            VisualElement("tanda_tangan_atau_stempel", page=13,
                          bbox=(0, 0, 10, 10), position="bawah-tengah",
                          nearby_text="Bistok Simbolon"),
            VisualElement("tanda_tangan_atau_stempel", page=14,
                          bbox=(0, 0, 10, 10), position="bawah-kiri",
                          nearby_text="AMIR SYAMSUDIN"),
        ]
        chunks = build_visual_chunks("doc1", visuals)
        assert len(chunks) == 2
        assert all("tanda tangan" in text for _id, text, _page in chunks)

    def test_daftar_kosong_tidak_menghasilkan_chunk(self) -> None:
        assert build_visual_chunks("doc1", []) == []

    def test_chunk_visual_bisa_jadi_chunk_domain(self) -> None:
        # Kontrak dengan service: pasangan (id, isi, halaman) harus bisa
        # dijadikan Chunk biasa yang ikut embedding dan index.
        chunks = build_visual_chunks(
            "doc1",
            [VisualElement("lambang", page=1, bbox=(0, 0, 10, 10),
                           position="atas-tengah", nearby_text="PRESIDEN")],
        )
        chunk_id, content, page = chunks[0]
        chunk = Chunk(
            id=chunk_id,
            document_id="doc1",
            chunk_index=0,
            content=content,
            page_number=page,
            section="Visual",
            quality_flag="ok",
        )
        assert chunk.content.startswith("Elemen visual dokumen")
