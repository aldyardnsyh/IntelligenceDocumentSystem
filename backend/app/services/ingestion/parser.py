"""Ekstraksi teks dari berkas yang diunggah.

Parsing sendiri bukan bagian yang rumit, tapi tiga hal di sini menentukan
apakah hasilnya berguna:

1. **PDF di luar scope OCR**. PDF hasil pindai tidak punya layer
   teks, dan hasilnya dokumen kosong. Itu harus gagal dengan pesan yang
   jelas, bukan diam-diam mengindeks nol byte.
2. **Nomor halaman harus dipertahankan.** Tanpa itu, Citation Card tidak
   bisa menampilkan "Hal. 12" dan yang bisa ditampilkan cuma nomor chunk.
3. **Deteksi PDF terenkripsi.** Berkas seperti itu gagal dengan pesan
   spesifik supaya pengguna tahu harus menghapus password-nya.
"""

from __future__ import annotations

import io
import logging
import re
import time
from dataclasses import dataclass, field

from app.core.config import Settings

logger = logging.getLogger(__name__)

#: Batas karakter per halaman sebelum dianggap mencurigakan (biasanya hasil
#: OCR yang gagal, atau PDF yang hanya berisi gambar).
MIN_CHARS_PER_PAGE = 40

#: Batas waktu satu dokumen PDF diproses. Nilai ini jauh di atas kebutuhan
#: dokumen normal (ratusan halaman selesai dalam hitungan detik), tapi cukup
#: rendah untuk mencegah satu unggahan menahan worker tanpa batas.
PDF_PARSE_TIMEOUT_SECONDS = 120.0

#: Batas jumlah halaman. Dokumen kerja normal jarang melewati ini; yang
#: melewatinya biasanya hasil ekspor berulang atau berkas yang dibuat untuk
#: membebani parser.
MAX_PDF_PAGES = 3000

#: Karakter markup yang dibuang dari nama berkas. Nama berkas ikut masuk ke
#: konteks prompt LLM, jadi membiarkannya berarti membuka jalur prompt
#: injection, bukan hanya masalah tampilan.
_MARKUP_RE = re.compile(r"[<>{}\[\]|`^$]")


class ParseError(RuntimeError):
    """Berkas tidak bisa dibaca. Pesannya ditulis untuk ditampilkan."""


@dataclass(slots=True)
class ParsedPage:
    """Satu halaman dokumen."""

    text: str
    page_number: int


@dataclass(slots=True)
class ParsedDocument:
    """Hasil parsing lengkap."""

    pages: list[ParsedPage]
    page_count: int
    #: True kalau sumbernya PDF. Menentukan cara pemeriksaan isi dijalankan:
    #: untuk PDF, halaman kosong berarti hasil pindai; untuk TXT/MD, isi
    #: pendek itu valid.
    is_pdf: bool = False
    #: Nomor halaman yang tidak menghasilkan teks sama sekali. PDF hasil
    #: pindai atau sebagian korup punya pola ini; pengguna perlu tahu kalau
    #: sebagian isi dokumennya tidak ikut terindeks.
    empty_pages: list[int] = field(default_factory=list)

    @property
    def full_text(self) -> str:
        r"""Gabung semua halaman dengan pemisah yang jelas.

        Pemisah ``\f`` (form feed) dipakai supaya nomor halaman masih bisa
        dipulihkan saat chunking.
        """
        return "\f".join(page.text for page in self.pages)

    def looks_empty(self) -> bool:
        """True kalau dokumen tidak punya teks yang bisa dipakai.

        Aturan berbeda per format, dan itu disengaja:

        - **PDF** memakai ambang ``MIN_CHARS_PER_PAGE`` per halaman. Halaman
          yang nyaris kosong adalah tanda kuat dokumen hasil pindai,
          dan itu memang harus gagal dengan pesan yang jelas.
        - **TXT/Markdown** tidak memakai ambang itu sama sekali. Catatan
          20 karakter adalah dokumen yang valid dan sering muncul; menolaknya
          berarti mengeluarkan dokumen yang jelas bisa dibaca. Syaratnya
          hanya "ada isi selain spasi", dan itu sudah diperiksa di
          ``_parse_text``.
        """
        if not self.pages:
            return True
        if not any(page.text.strip() for page in self.pages):
            return True
        if self.is_pdf:
            filled = sum(
                1 for page in self.pages if len(page.text.strip()) >= MIN_CHARS_PER_PAGE
            )
            return filled == 0
        return False


def sanitize_filename(raw: str) -> str:
    r"""Bersihkan nama berkas dari metadata klien sebelum disimpan.

    Nama berkas berasal penuh dari klien dan dipakai sebagai metadata Chroma,
    isi citation card, dan konteks prompt. Tanpa sanitasi:
    - separator path (``../``, ``C:\\``) ikut tersimpan dan menyesatkan di UI
      walau saat ini tidak pernah dipakai untuk menulis berkas;
    - karakter kontrol/newline merusak tampilan daftar dokumen;
    - markup dalam nama bisa jadi XSS tersimpan di frontend atau menyuntik
      instruksi ke prompt LLM.
    """
    name = raw.replace("\\", "/").rsplit("/", 1)[-1]
    name = "".join(char for char in name if char.isprintable()).strip()
    # Tanda markup dibuang di server, bukan hanya saat dirender: nama berkas
    # ikut masuk ke konteks prompt LLM, jadi markup di dalamnya adalah jalur
    # prompt injection, terlepas dari apakah frontend kebal XSS atau tidak.
    name = _MARKUP_RE.sub("", name)
    name = re.sub(r"\s+", " ", name).strip(" .")

    if not name:
        raise ParseError("Nama berkas tidak terbaca.")

    stem, dot, ext = name.rpartition(".")
    if dot and len(ext) <= 10:
        stem, ext = stem, ext
    else:
        stem, ext = name, ""

    # Batas aman untuk filesystem dan kolom database. Ekstensi dipertahankan
    # supaya validasi format tetap bekerja.
    stem = stem[:180]
    ext = ext[:10]
    return f"{stem}.{ext}" if ext else stem


def validate_extension(filename: str, settings: Settings) -> str:
    """Pastikan ekstensi didukung, kembalikan lowercase-nya."""
    lowered = filename.lower()
    if not any(lowered.endswith(ext) for ext in settings.accepted_extensions):
        supported = ", ".join(ext.lstrip(".") for ext in settings.accepted_extensions)
        raise ParseError(f"Format tidak didukung. Gunakan berkas: {supported}.")
    return lowered


def validate_size(size_bytes: int, settings: Settings) -> None:
    """Tolak berkas yang melebihi batas."""
    if size_bytes <= 0:
        raise ParseError("Berkas kosong.")
    if size_bytes > settings.max_file_size_bytes:
        limit_mb = settings.max_file_size_bytes / (1024 * 1024)
        raise ParseError(f"Ukuran berkas melebihi batas {limit_mb:.0f} MB.")


def _parse_pdf(data: bytes) -> ParsedDocument:
    """Ekstrak teks per halaman dari PDF.

    ``pypdf`` dipilih karena ringan dan murni Python; ``pdfplumber`` lebih
    akurat untuk tata letak rumit tapi menambah dependensi besar.

    ## Kenapa ada dua batas keras di sini

    Isi berkas PDF sepenuhnya dikendalikan pengunggah, dan pypdf adalah
    parser yang membaca struktur yang bisa dibuat berlapis-lapis dengan
    sengaja. Riwayat CVE-nya menunjukkan polanya: bukan eksekusi kode, tapi
    dokumen yang membuat parser berjalan sangat lama atau memakan memori
    sangat besar. Versi minimum di ``pyproject.toml`` menutup yang sudah
    diketahui, tapi ini pertahanan lapis kedua supaya kelas serangan yang
    sama tidak bisa dipakai lagi lewat celah baru.

    1. **Batas waktu per dokumen.** Satu PDF tidak boleh menyita worker
       lebih dari ``PDF_PARSE_TIMEOUT_SECONDS``. Tanpa ini, satu unggahan
       cukup untuk menahan satu worker sampai prosesnya dibunuh.
    2. **Batas jumlah halaman.** ``MAX_PDF_PAGES`` menolak lebih awal,
       sebelum per halaman diekstrak. Memeriksa ``len(reader.pages)`` saja
       tidak cukup: pada PDF tertentu daftar itu dibangun malas dan
       panjangnya baru diketahui sambil berjalan.

    Batas waktu diperiksa di antara halaman, bukan dengan alarm yang
    memotong di tengah C call. Itu disengaja: memotong pypdf di tengah
    operasinya bisa meninggalkan state yang tidak jelas, sedangkan
    pemeriksaan per halaman sudah menutup kasus yang realistis (dokumen
    dengan halaman sangat banyak atau satu halaman yang sangat berat).
    """
    try:
        from pypdf import PdfReader
    except ImportError as exc:  # pragma: no cover - ketergantungan wajib
        raise ParseError("Pustaka pypdf belum terpasang di server.") from exc

    try:
        reader = PdfReader(io.BytesIO(data))
    except Exception as exc:  # noqa: BLE001
        raise ParseError(f"Berkas PDF tidak bisa dibaca: {exc}") from exc

    if reader.is_encrypted:
        # pypdf masih bisa membuka dokumen terenkripsi, tapi teksnya tidak
        # terbaca tanpa password.
        try:
            can_read = reader.decrypt("")
        except Exception:  # noqa: BLE001
            can_read = False
        if not can_read:
            raise ParseError("PDF ini diproteksi password. Hapus passwordnya lalu unggah ulang.")

    pages: list[ParsedPage] = []
    empty_pages: list[int] = []
    deadline = time.monotonic() + PDF_PARSE_TIMEOUT_SECONDS

    for index, page in enumerate(reader.pages, start=1):
        if index > MAX_PDF_PAGES:
            raise ParseError(
                f"PDF ini punya lebih dari {MAX_PDF_PAGES} halaman. "
                "Pecah dokumennya lalu unggah bagian yang dibutuhkan."
            )
        if time.monotonic() > deadline:
            raise ParseError(
                "PDF ini terlalu berat untuk diproses. Coba pecah dokumennya "
                "atau ekspor ulang tanpa kompresi berlapis."
            )
        try:
            text = page.extract_text() or ""
        except Exception as exc:  # noqa: BLE001
            logger.warning("Gagal ekstrak halaman %d: %s", index, exc)
            text = ""
        stripped = text.strip()
        if not stripped:
            empty_pages.append(index)
        pages.append(ParsedPage(text=stripped, page_number=index))

    if not pages:
        raise ParseError("PDF tidak berisi halaman yang bisa dibaca.")

    parsed = ParsedDocument(pages=pages, page_count=len(pages), is_pdf=True)
    parsed.empty_pages = empty_pages
    return parsed


def _parse_text(raw: bytes, filename: str) -> ParsedDocument:
    """Baca TXT atau Markdown.

    Deteksi encoding dengan urutan tebakan yang umum dipakai. Berkas
    Indonesia sering bukan UTF-8 murni.
    """
    # ``utf-8-sig`` dicoba lebih dulu: file ber-BOM berhasil di-decode sebagai
    # ``utf-8`` biasa, hanya dengan karakter ``﻿`` menempel di awal teks.
    for encoding in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            text = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:  # pragma: no cover - latin-1 tidak pernah gagal
        raise ParseError("Encoding teks tidak dikenali.")

    if not text.strip():
        raise ParseError("Berkas teks tidak berisi karakter yang bisa dibaca.")

    # Teks tidak berpaginasikan, jadi satu halaman dengan nomor None. Citation
    # Card lalu menampilkan nomor chunk, karena sitasi boleh menunjuk halaman
    # atau chunk.
    return ParsedDocument(pages=[ParsedPage(text=text.strip(), page_number=None)], page_count=1)


def parse_document(filename: str, data: bytes, settings: Settings) -> ParsedDocument:
    """Titik masuk parsing berkas.

    Args:
        filename: Nama berkas asli, dipakai untuk menentukan format.
        data: Isi berkas mentah.
        settings: Konfigurasi, untuk batas ukuran dan daftar ekstensi.

    Raises:
        ParseError: Kalau berkas tidak didukung, rusak, atau tidak berisi teks.
    """
    validate_extension(filename, settings)
    validate_size(len(data), settings)

    lowered = filename.lower()
    parsed = _parse_pdf(data) if lowered.endswith(".pdf") else _parse_text(data, filename)

    if parsed.looks_empty():
        raise ParseError(
            "Tidak ada teks yang bisa dibaca dari berkas ini. "
            "Kalau ini hasil pindai, ekstraksi teksnya tidak didukung di versi ini."
        )

    return parsed
