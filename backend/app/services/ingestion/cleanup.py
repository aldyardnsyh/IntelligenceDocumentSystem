"""Pembersihan teks hasil ekstraksi PDF.

Aturannya sengaja konservatif. Yang dibuang hanya pola yang nyata-nyata
artefak halaman — nomor halaman, cap "PRESIDEN REPUBLIK INDONESIA" di kaki
halaman, dan baris lanjutan ber-"..." milik penanda halaman — bukan "kata
yang tampak salah". Memperbaiki kata secara buta berbahaya: "Undang-Undan g"
memang bisa disambung, tapi aturan yang sama merusak kata sah seperti "ke"
menjadi bagian kata sebelumnya. Perbaikan teks yang benar-benar rusak bukan
tugas regex — itu tugas jalur vision OCR yang membaca citra halaman.

Pembersihan ini hanya diterapkan pada teks yang diekstrak dari PDF, bukan
pada TXT/Markdown yang diunggah pengguna: isi yang pengguna tulis sendiri
tidak boleh diubah sedikit pun.
"""

from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher

#: Cap kaki halaman Lembaran Negara, ditulis sebagai satu baris.
_GAZETTE_FOOTER = "PRESIDENREPUBLIKINDONESIA"

#: Normalisasi sebuah baris untuk perbandingan fuzzy: hanya huruf besar,
#: tanpa spasi dan tanda baca. OCR yang salah membaca "O" menjadi "0" atau
#: menyisipkan spasi di tengah kata ("REP UBL IK") tetap terdeteksi.
_LINE_NORMALIZE_RE = re.compile(r"[^A-Za-z]")

#: Baris yang seluruhnya nomor halaman ("\ 2 -", "- 12 -", "12").
_PAGE_NUMBER_RE = re.compile(r"^[\\-]?\s*\d{1,3}\s*-?\s*$")

#: Baris penanda halaman ber-"...". Penampil dokumen lembaran negara menempel
#: awal kalimat halaman berikutnya di kaki halaman; baris ini duplikat dari
#: teks yang utuh di halaman itu sendiri, jadi membuangnya tidak menghilangkan
#: isi apa pun.
_MARGIN_ELLIPSIS_RE = re.compile(r"\.\.\.\s*$")

#: Panjang maksimum baris yang dianggap cap/kaki halaman, bukan isi.
_FOOTER_MAX_CHARS = 60


def _is_gazette_footer(line: str) -> bool:
    """True kalau baris adalah variasi cap "PRESIDEN REPUBLIK INDONESIA".

    Perbandingan fuzzy dengan ambang longgar: teks OCR yang salah baca
    ("PRES I OEN REPUBLIK INOONESIA", "PRESIOEN REPUBLIK INDONESIA") tetap
    cocok, sementara kalimat biasa tidak mungkin mencapai kemiripan itu.
    """
    cleaned = _LINE_NORMALIZE_RE.sub("", line).upper()
    if not cleaned or len(cleaned) > 40:
        return False
    return SequenceMatcher(None, cleaned, _GAZETTE_FOOTER).ratio() >= 0.72


def is_noise_line(line: str) -> bool:
    """True kalau baris adalah artefak halaman, bukan isi dokumen.

    Publik karena deteksi kualitas text-layer (``text_quality``) memakai
    rasio baris noise yang sama sebagai salah satu sinyalnya: dokumen dengan
    text-layer bagus nyaris tidak punya baris seperti ini.
    """
    stripped = line.strip()
    if not stripped:
        return False
    if len(stripped) <= _FOOTER_MAX_CHARS:
        if _PAGE_NUMBER_RE.match(stripped):
            return True
        if _is_gazette_footer(stripped):
            return True
    return bool(_MARGIN_ELLIPSIS_RE.search(stripped))


def strip_noise_lines(text: str) -> str:
    """Buang baris-baris artefak halaman dari teks ekstraksi."""
    if not text:
        return text
    lines = text.split("\n")
    kept = [line for line in lines if not is_noise_line(line)]
    return "\n".join(kept)


def clean_page_text(text: str) -> str:
    """Bersihkan teks satu halaman hasil ekstraksi PDF.

    Urutannya: normalisasi unicode, buang baris noise, lalu rapikan whitespace.
    Normalisasi NFKC wajib lebih dulu: PP-OCR terlatih pada korpus CJK sering
    mengeluarkan tanda kurung/dash fullwidth ("（1）" untuk "(1)"), dan itu
    merusak regex ayat/butir maupun pencarian "ayat (3)".
    """
    cleaned = unicodedata.normalize("NFKC", text)
    cleaned = strip_noise_lines(cleaned)
    cleaned = re.sub(r"[ \t]+", " ", cleaned)
    cleaned = re.sub(r" *\n *", "\n", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()
