"""Penilaian kualitas text-layer PDF halaman per halaman.

PDF "hasil pindai" punya dua wajah: sama sekali tanpa text-layer (halaman
kosong saat diekstrak), atau punya text-layer sisa OCR yang kualitasnya
buruk — PDF Lembaran Negara dari BPK masuk kelompok kedua: teksnya ada, tapi
urutan baca kacau karena tata letak dua kolom, dan kata-katanya terpecah
("Undang-Undan g", "Tah un").

Kasus kedua yang paling berbahaya, karena dokumen itu lolos pemeriksaan
"tidak kosong" dan diindeks apa adanya: retrieval lalu menemukan potongan
teks yang benar secara kata kunci tapi salah secara isi. Penilaian di sini
mendeteksi keduanya lewat sinyal statistik yang murah dihitung, jadi
keputusan "perlu OCR atau tidak" bisa diambil sebelum embedding dikeluarkan.
"""

from __future__ import annotations

import re
import statistics
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Protocol

from app.services.ingestion.cleanup import is_noise_line


class PageLike(Protocol):
    """Halaman yang bisa dinilai: cukup punya ``text`` dan ``page_number``.

    Dibuat sebagai Protocol, bukan import ``ParsedPage`` dari parser, karena
    parser juga mengimpor modul ini untuk mengisi ``needs_ocr`` — import
    langsung akan melingkar. ParsedPage memenuhi kontrak ini secara struktural.
    """

    text: str
    page_number: int | None

#: Halaman di bawah ambang ini dianggap kosong. Nilainya sama dengan
#: ``MIN_CHARS_PER_PAGE`` di parser supaya keduanya bercerita hal yang sama.
EMPTY_PAGE_CHARS = 40

#: Rasio token satu huruf terhadap seluruh token huruf, dihitung level
#: dokumen. Teks Indonesia yang utuh hampir tidak punya token satu huruf yang
#: berdiri sendiri; "Undang-Undan g" dan "Tah un" menghasilkannya dalam jumlah
#: besar. Diukur pada korpus nyata: text-layer rusak Perpres 76/2013 = 6.6%,
#: teks bersih dari struktur resmi = 1.8%, dokumen SOP = 0%. Ambang 5% dipilih
#: di tengah jurang itu. Angka dihitung agregat, bukan maksimum per halaman,
#: supaya satu halaman padat butir "a."-"f." tidak memicu OCR sendirian.
SINGLE_CHAR_TOKEN_RATIO_MAX = 0.05

#: Rasio baris noise (artefak kaki halaman) terhadap seluruh baris.
NOISE_LINE_RATIO_MAX = 0.10

#: Porsi halaman kosong sebelum dokumen dianggap perlu OCR.
EMPTY_PAGE_RATIO_MAX = 0.20

#: Token = deretan huruf. Digit dikeluarkan sengaja: angka satu digit ("Pasal
#: 1", tahun "1" pada butir) adalah isi sah dokumen, sedangkan satu huruf
#: yang berdiri sendiri hampir selalu sisa kata terpecah.
_TOKEN_RE = re.compile(r"[A-Za-zÀ-ÿ]+")


def _token_stats(text: str) -> tuple[int, int]:
    """Jumlah token huruf dan jumlah token satu huruf."""
    tokens = _TOKEN_RE.findall(text)
    single = sum(1 for token in tokens if len(token) == 1)
    return len(tokens), single


def _noise_line_ratio(text: str) -> float:
    """Porsi baris yang polanya artefak halaman, 0.0 kalau tidak ada baris."""
    lines = [line for line in text.split("\n") if line.strip()]
    if not lines:
        return 0.0
    noise = sum(1 for line in lines if is_noise_line(line))
    return noise / len(lines)


@dataclass(slots=True)
class PageTextSignal:
    """Sinyal kualitas teks satu halaman."""

    page_number: int | None
    char_count: int
    empty: bool
    single_char_token_ratio: float
    noise_line_ratio: float


@dataclass(slots=True)
class TextQualityReport:
    """Hasil penilaian text-layer satu dokumen.

    ``reasons`` memuat alasan keputusan dalam bentuk yang bisa langsung
    ditulis ke log — saat operator bertanya kenapa dokumennya di-OCR (atau
    tidak), jawabannya harus bisa dibaca, bukan sekadar boolean.
    """

    page_signals: list[PageTextSignal] = field(default_factory=list)
    empty_page_ratio: float = 0.0
    median_chars: float = 0.0
    single_char_token_ratio: float = 0.0
    noise_line_ratio: float = 0.0
    needs_ocr: bool = False
    reasons: list[str] = field(default_factory=list)


def assess_text_layer(pages: Iterable[PageLike]) -> TextQualityReport:
    """Nilai kualitas text-layer dan putuskan apakah perlu OCR.

    Keputusan diambil per **dokumen**, bukan per halaman: mencampur teks
    text-layer untuk sebagian halaman dan hasil OCR untuk sisanya menghasilkan
    gaya teks yang tidak konsisten di satu dokumen yang sama, dan itu lebih
    sulit didiagnosis daripada salah keputusan tunggal.
    """
    report = TextQualityReport()

    signals: list[PageTextSignal] = []
    total_tokens = 0
    single_char_tokens = 0
    for page in pages:
        text = page.text or ""
        char_count = len(text.strip())
        token_count, single_count = _token_stats(text)
        if char_count >= EMPTY_PAGE_CHARS:
            # Halaman nyaris kosong tidak ikut agregasi: satu-dua huruf sisa
            # di halaman kosong akan mendistorsi rasio seluruh dokumen.
            total_tokens += token_count
            single_char_tokens += single_count
        signals.append(
            PageTextSignal(
                page_number=page.page_number,
                char_count=char_count,
                empty=char_count < EMPTY_PAGE_CHARS,
                single_char_token_ratio=(single_count / token_count) if token_count else 0.0,
                noise_line_ratio=_noise_line_ratio(text),
            )
        )
    report.page_signals = signals

    filled = [signal for signal in signals if not signal.empty]
    report.empty_page_ratio = (
        (len(signals) - len(filled)) / len(signals) if signals else 1.0
    )

    non_empty_texts = [
        (page.text or "") for page, signal in zip(pages, signals, strict=True) if not signal.empty
    ]
    if non_empty_texts:
        report.median_chars = statistics.median(len(text.strip()) for text in non_empty_texts)
        report.single_char_token_ratio = (
            single_char_tokens / total_tokens if total_tokens else 0.0
        )
        report.noise_line_ratio = max(
            (signal.noise_line_ratio for signal in filled), default=0.0
        )

    if report.empty_page_ratio > EMPTY_PAGE_RATIO_MAX:
        report.needs_ocr = True
        report.reasons.append(
            f"{report.empty_page_ratio:.0%} halaman kosong atau nyaris kosong"
        )
    if filled and report.single_char_token_ratio > SINGLE_CHAR_TOKEN_RATIO_MAX:
        report.needs_ocr = True
        report.reasons.append(
            f"rasio token satu huruf {report.single_char_token_ratio:.1%} "
            "(ciri kata terpecah pada text-layer OCR rusak)"
        )
    if filled and report.noise_line_ratio > NOISE_LINE_RATIO_MAX:
        report.needs_ocr = True
        report.reasons.append(
            f"rasio baris noise {report.noise_line_ratio:.1%} "
            "(artefak kaki halaman)"
        )

    # ``median_chars`` sengaja bukan pemicu: halaman pendek itu sah (surat
    # satu paragraf, slide, formulir). Kepadatan rendah bukan kerusakan, dan
    # meng-OCR teks yang sebenarnya utuh hanya menambah biaya tanpa memperbaiki
    # apa pun. Nilainya tetap dilaporkan untuk audit.

    return report
