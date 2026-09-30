"""Test parser berkas.

Yang diuji di sini adalah perilaku yang harus gagal dengan pesan jelas, bukan
hanya parsing yang sukses. PDF terenkripsi dan berkas hasil pindai adalah dua
kasus yang paling sering membuat sistem gagal diam-diam.
"""

from __future__ import annotations

import io

import pytest

from app.core.config import Settings
from app.services.ingestion.parser import (
    ParseError,
    parse_document,
    validate_extension,
    validate_size,
)


def _make_encrypted_pdf(password: str) -> bytes:
    """Buat PDF kecil yang benar-benar dienkripsi oleh pypdf.

    PDF pseudo tidak bisa dipakai: `PdfReader` akan gagal lebih
    dulu dengan "startxref not found", sehingga jalur pemeriksaan enkripsi
    tidak pernah dieksekusi dan tesnya tidak menguji apa pun.
    """
    from pypdf import PdfWriter

    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    writer.encrypt(password)
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


@pytest.fixture
def config() -> Settings:
    return Settings()


class TestValidasi:
    def test_menolak_format_tidak_didukung(self, config: Settings) -> None:
        with pytest.raises(ParseError, match="Format tidak didukung"):
            validate_extension("gambar.png", config)

    def test_menerima_format_yang_didukung(self, config: Settings) -> None:
        for name in ("dokumen.pdf", "catatan.txt", "readme.md"):
            assert validate_extension(name, config) == name.lower()

    def test_menolak_berkas_kosong(self, config: Settings) -> None:
        with pytest.raises(ParseError, match="kosong"):
            validate_size(0, config)

    def test_menolak_berkas_terlalu_besar(self, config: Settings) -> None:
        with pytest.raises(ParseError, match="melebihi batas"):
            validate_size(config.max_file_size_bytes + 1, config)


class TestParseTeks:
    def test_membaca_markdown(self, config: Settings) -> None:
        parsed = parse_document("catatan.md", b"# Judul\n\nIsi catatan.", config)
        assert parsed.page_count == 1
        assert "Isi catatan." in parsed.full_text

    def test_membaca_utf8_dengan_bom(self, config: Settings) -> None:
        parsed = parse_document("catatan.txt", "\ufeffTeks dengan BOM".encode("utf-8-sig"), config)
        assert "Teks dengan BOM" in parsed.full_text

    def test_membaca_latin1(self, config: Settings) -> None:
        parsed = parse_document("catatan.txt", "Kata berkarakter: café".encode("latin-1"), config)
        assert "caf" in parsed.full_text

    def test_teks_tanpa_paginasi_punya_page_none(self, config: Settings) -> None:
        parsed = parse_document("catatan.txt", b"Isi tanpa halaman", config)
        # Page None membuat Citation Card menampilkan nomor chunk, bukan
        # nomor halaman yang tidak ada.
        assert parsed.pages[0].page_number is None

    def test_menolak_teks_kosong(self, config: Settings) -> None:
        with pytest.raises(ParseError, match="tidak berisi karakter"):
            parse_document("kosong.txt", b"   \n\n  ", config)

    def test_menolak_berkas_dengan_format_tidak_didukung(self, config: Settings) -> None:
        with pytest.raises(ParseError, match="Format tidak didukung"):
            parse_document("arsip.zip", b"PK\x03\x04", config)


class TestParsePdf:
    def test_menolak_pdf_terenkripsi(self, config: Settings) -> None:
        # PDF asli yang benar-benar dienkripsi, bukan PDF pseudo. PDF pseudo
        # gagal lebih dulu di ``PdfReader`` dengan "startxref not found", jadi
        # tidak pernah sampai ke pemeriksaan enkripsi, dan tes ini tidak
        # menguji apa pun.
        data = _make_encrypted_pdf("rahasia")
        with pytest.raises(ParseError, match="diproteksi password"):
            parse_document("rahasia.pdf", data, config)

    def test_password_benar_tidak_membuka_isi(self, config: Settings) -> None:
        """Dokumen terenkripsi harus ditolak, bukan dibuka dengan password.

        Server tidak punya kanal untuk meminta password dari pengguna, jadi
        PDF terenkripsi selalu ditolak. Yang diuji di sini adalah jangan
        sampai ada jalur yang membypassinya.
        """
        data = _make_encrypted_pdf("benar")
        with pytest.raises(ParseError, match="diproteksi password"):
            parse_document("rahasia.pdf", data, config)

    def test_menolak_data_pdf_rusak(self, config: Settings) -> None:
        with pytest.raises(ParseError, match="tidak bisa dibaca"):
            parse_document("rusak.pdf", b"%PDF-1.4\ncorrupt", config)
