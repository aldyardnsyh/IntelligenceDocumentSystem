"""Chunking mengikuti struktur dokumen peraturan Indonesia.

Dokumen peraturan (Perpres, UU, PP, Perda) punya struktur yang ketat:
BAB → Bagian → Pasal → ayat → butir. Struktur itulah unit makna alaminya —
"Penyelenggara wajib menyelesaikan setiap pengaduan paling lambat 60 hari"
hanya bermakna lengkap kalau pembacanya tahu itu Pasal 12 ayat (3).

Chunker paragraf generik mengabaikan struktur itu: batas chunk jatuh di
tengah Pasal, judul BAB tercampur dengan isi Pasal lain, dan retrieval
mendapat potongan yang sulit disitasi. Parser di sini membaca struktur
tersebut dari teks lalu membangun chunk **per Pasal**, dengan baris pertama
setiap chunk berisi konteks lengkapnya:

    BAB II – PENGELOLAAN PENGADUAN · Bagian Kedua – Sarana Pengaduan · Pasal 5

Header itu bukan hiasan: model embedding membacanya bersama isi chunk, jadi
pertanyaan "sarana pengaduan itu apa" menemukan Pasal yang benar meski kata
"Bagian Kedua" tidak pernah muncul di pertanyaan.

Fallback-nya aman: teks yang tidak terdeteksi sebagai dokumen legal (kurang
dari dua heading Pasal) mengembalikan daftar kosong dan pemanggil melanjutkan
ke chunking paragraf generik.
"""

from __future__ import annotations

import bisect
import logging
import re
import statistics
from dataclasses import dataclass

from app.services.ingestion.chunker import (
    TextSpan,
    _split_long_paragraph,
    normalize_text,
)

logger = logging.getLogger(__name__)

#: "BAB II" — judul bisa di baris yang sama atau baris berikutnya. Spasi
#: sengaja opsional: PP-OCR pada teks tebal kerap menyatu ("BABI" = "BAB I").
_BAB_RE = re.compile(r"^BAB\s*([IVXLCDM]+)\b\s*(.*)$", re.IGNORECASE)

#: Ordinal Bagian yang lazim. Daftar eksplisit, bukan pola bebas, supaya kata
#: "bagian" yang muncul di tengah kalimat tidak salah terbaca sebagai heading.
_BAGIAN_ORDINALS = (
    "Kesatu",
    "Kedua",
    "Ketiga",
    "Keempat",
    "Kelima",
    "Keenam",
    "Ketujuh",
    "Kedelapan",
    "Kesembilan",
    "Kesepuluh",
    "Kesebelas",
    "Keduabelas",
    "Ketigabelas",
    "Keempatbelas",
    "Kelimabelas",
    "Keenambelas",
    "Ketujuhbelas",
    "Kedelapanbelas",
    "Kesembilanbelas",
    "Keduapuluh",
)
_BAGIAN_RE = re.compile(
    r"^Bagian\s*(" + "|".join(_BAGIAN_ORDINALS) + r")\b\s*\.?:?\s*(.*)$"
)

#: Heading Pasal: nomor sendirian di barisnya. Spasi sengaja opsional karena
#: OCR pada judul tebal kerap menyatukan "Pasal 1" menjadi "Pasal1".
_PASAL_RE = re.compile(r"^Pasal\s*(\d{1,3})\s*\.?:?\s*$")

#: Ayat "(1)" di awal baris, butir "1." atau "a." di awal baris — keduanya
#: dipakai sebagai batas pemecahan Pasal panjang. Spasi setelah penanda
#: sengaja opsional: OCR kerap menggabung "(1)Setiap..." dan
#: "1.Pelayananpublik" menjadi satu token.
_AYAT_LINE_RE = re.compile(r"(?m)^\((\d{1,2})\)\s?")
_BUTIR_LINE_RE = re.compile(r"(?m)^(?:\d{1,2}|[a-z])\.")

#: Penanda bagian penetapan/pengundangan di akhir dokumen.
_CLOSING_RE = re.compile(
    r"^(?:Ditetapkan di|Diundangkan di|Salinan sesuai dengan aslinya)\b",
    re.IGNORECASE,
)

#: Ukuran minimum bagian non-Pasal untuk dijadikan chunk sendiri.
_PREAMBLE_MIN_CHARS = 100
_CLOSING_MIN_CHARS = 150

#: Panjang maksimum baris yang dianggap judul BAB/Bagian.
_TITLE_MAX_CHARS = 100

#: Overlap kalimat saat satu ayat/butir sendiri melebihi batas chunk.
_SENTENCE_OVERLAP = 50


@dataclass(slots=True)
class _PasalHeading:
    """Satu heading Pasal beserta konteks BAB/Bagian saat itu."""

    nomor: int
    heading_start: int
    heading_len: int
    bab: str | None
    judul_bab: str | None
    bagian: str | None
    judul_bagian: str | None


@dataclass(slots=True)
class _LegalStructure:
    pasals: list[_PasalHeading]
    preamble_end: int | None
    closing_start: int | None


def _page_starts(document: str) -> list[int]:
    r"""Offset awal tiap halaman dalam dokumen yang sudah dinormalisasi.

    Halaman digabung dengan pemisah ``\n\f\n``; offset dihitung kumulatif
    sehingga tidak perlu memindai ulang dokumen untuk memetakan offset ke
    nomor halaman. Dokumen tanpa pemisah (TXT, PDF satu halaman) tidak
    dipaginasikan.
    """
    if "\f" not in document:
        return [0]
    starts = [0]
    cursor = 0
    separator_length = len("\n\f\n")
    for page_text in document.split("\f"):
        cursor += len(page_text) + separator_length
        starts.append(cursor)
    return starts


def _page_number_for(page_starts: list[int], offset: int) -> int | None:
    """Nomor halaman (mulai 1) tempat offset berada; None kalau tanpa paginasi."""
    if len(page_starts) <= 1:
        return None
    return bisect.bisect_right(page_starts, offset)


def _is_heading(line: str) -> bool:
    """True kalau baris adalah heading struktur, bukan judul atau isi."""
    return bool(
        _PASAL_RE.match(line) or _BAB_RE.match(line) or _BAGIAN_RE.match(line)
    )


def _next_title(lines: list[str], index: int) -> str | None:
    """Judul BAB/Bagian yang ditulis di baris setelah heading-nya.

    Format resmi selalu menaruh judul tepat setelah heading ("Bagian Kedua"
    lalu "Sarana Pengaduan"), jadi baris berikutnya yang bukan heading dan
    tidak diakhiri tanda baca kalimat diambil apa adanya — baik judul yang
    ditulis kapital ("KETENTUAN UMUM") maupun kapital di awal kata
    ("Sarana Pengaduan").
    """
    for candidate in lines[index + 1 : index + 3]:
        stripped = candidate.strip()
        if not stripped:
            continue
        if _is_heading(stripped) or len(stripped) > _TITLE_MAX_CHARS:
            return None
        if stripped.endswith((";", ":", ",")):
            return None
        return stripped
    return None


def _parse_structure(document: str) -> _LegalStructure | None:
    """Baca struktur legal dari teks yang sudah dinormalisasi.

    Satu lintasan atas baris-baris dokumen; konteks BAB/Bagian berlaku mulai
    heading-nya masing-masing. Pasal dengan nomor duplikat (artefak OCR)
    dibuang: lebih baik kehilangan satu Pasal daripada mengindeks teks yang
    tercampur antar Pasal.
    """
    lines = document.split("\n")
    # Offset tiap baris dihitung saat pemisahan, bukan dengan str.find:
    # offset kumulatif selalu benar, sekalipun ada baris kosong beruntun.
    offsets: list[int] = []
    cursor = 0
    for line in lines:
        offsets.append(cursor)
        cursor += len(line) + 1

    pasals: list[_PasalHeading] = []
    bab: str | None = None
    judul_bab: str | None = None
    bagian: str | None = None
    judul_bagian: str | None = None
    preamble_end: int | None = None
    closing_start: int | None = None

    for index, (line, offset) in enumerate(zip(lines, offsets, strict=True)):
        stripped = line.strip()
        if not stripped:
            continue

        if closing_start is None and _CLOSING_RE.match(stripped):
            closing_start = offset
            continue

        bab_match = _BAB_RE.match(stripped)
        if bab_match:
            bab = bab_match.group(1).upper()
            judul_bab = bab_match.group(2).strip() or _next_title(lines, index)
            continue

        bagian_match = _BAGIAN_RE.match(stripped)
        if bagian_match:
            bagian = bagian_match.group(1)
            judul_bagian = bagian_match.group(2).strip() or _next_title(lines, index)
            continue

        pasal_match = _PASAL_RE.match(stripped)
        if pasal_match:
            nomor = int(pasal_match.group(1))
            if any(existing.nomor == nomor for existing in pasals):
                logger.warning(
                    "Heading Pasal %d muncul dua kali; salinan kedua diabaikan.",
                    nomor,
                )
                continue
            pasals.append(
                _PasalHeading(
                    nomor=nomor,
                    heading_start=offset,
                    heading_len=len(stripped),
                    bab=bab,
                    judul_bab=judul_bab,
                    bagian=bagian,
                    judul_bagian=judul_bagian,
                )
            )
            if preamble_end is None:
                preamble_end = offset

    if len(pasals) < 2:
        return None

    return _LegalStructure(
        pasals=pasals,
        preamble_end=preamble_end,
        closing_start=closing_start,
    )


def _section_header(pasal: _PasalHeading) -> str:
    """Baris konteks di awal chunk: BAB, Bagian, lalu nomor Pasal."""
    parts: list[str] = []
    if pasal.bab:
        parts.append(f"BAB {pasal.bab}" + (f" – {pasal.judul_bab}" if pasal.judul_bab else ""))
    if pasal.bagian:
        parts.append(
            f"Bagian {pasal.bagian}"
            + (f" – {pasal.judul_bagian}" if pasal.judul_bagian else "")
        )
    parts.append(f"Pasal {pasal.nomor}")
    return " · ".join(parts)


def _body_pieces(
    document: str, body_start: int, body_end: int, max_chars: int, overlap: int
) -> list[tuple[int, int]]:
    """Pecah isi satu Pasal menjadi potongan ≤ ``max_chars``.

    Batas ayat/butir dipakai lebih dulu — itu unit makna berikutnya setelah
    Pasal. Baru kalau satu ayat sendiri melebihi batas, pemecahan turun ke
    batas kalimat (``_split_long_paragraph``).
    """
    body = document[body_start:body_end]
    if len(body.strip()) <= max_chars:
        return [(body_start, body_end)]

    boundaries = [match.start() for match in _AYAT_LINE_RE.finditer(body)]
    if len(boundaries) < 2:
        boundaries = [match.start() for match in _BUTIR_LINE_RE.finditer(body)]

    if len(boundaries) < 2:
        pieces = _split_long_paragraph(body, body_start, max_chars, overlap)
        return [(piece.char_start, piece.char_end) for piece in pieces]

    segment_starts = [0, *boundaries]
    segments = [
        (
            segment_starts[i],
            segment_starts[i + 1] if i + 1 < len(segment_starts) else len(body),
        )
        for i in range(len(segment_starts))
    ]

    packed: list[tuple[int, int]] = []
    current_start, current_end = segments[0]
    for segment_start, segment_end in segments[1:]:
        if segment_end - current_start <= max_chars:
            current_end = segment_end
            continue
        packed.append((current_start, current_end))
        current_start, current_end = segment_start, segment_end
    packed.append((current_start, current_end))

    pieces: list[tuple[int, int]] = []
    for piece_start, piece_end in packed:
        if piece_end - piece_start > max_chars:
            pieces.extend(
                (span.char_start, span.char_end)
                for span in _split_long_paragraph(
                    body[piece_start:piece_end],
                    body_start + piece_start,
                    max_chars,
                    overlap,
                )
            )
        else:
            pieces.append((body_start + piece_start, body_start + piece_end))
    return pieces


def _chunks_for_body(
    *,
    header: str,
    section_label: str,
    body_start: int,
    body_end: int,
    document: str,
    max_chars: int,
    overlap: int,
    page_starts: list[int],
    first_page_offset: int | None = None,
) -> list[TextSpan]:
    """Bangun chunk ber-header untuk satu rentang body.

    ``first_page_offset`` menunjuk posisi heading bagian itu (mis. baris
    "Pasal 2"). Nomor halaman chunk pertama diambil dari situ, bukan dari
    awal body — heading bisa jatuh di ujung halaman sebelumnya, dan sitasi
    "Hal. 5" harus menunjuk halaman tempat Pasal itu diumumkan.
    """
    spans: list[TextSpan] = []
    pieces = _body_pieces(document, body_start, body_end, max_chars, overlap)
    # Small-to-big: kalau badan terpecah jadi lebih dari satu potongan, setiap
    # potongan membawa badan PASAL utuhnya sebagai parent_text. Potongan tetap
    # yang diindeks (ringkas, akurat untuk retrieval); pasal utuh dipakai saat
    # menjawab sebagai konteks ekspansi — satu Pasal adalah unit maknanya.
    parent = document[body_start:body_end] if len(pieces) > 1 else None
    for piece_index, (piece_start, piece_end) in enumerate(pieces):
        body = document[piece_start:piece_end]
        page_offset = (
            first_page_offset if piece_index == 0 and first_page_offset is not None else piece_start
        )
        spans.append(
            TextSpan(
                content=f"{header}\n\n{body}",
                char_start=piece_start,
                char_end=piece_end,
                page_number=_page_number_for(page_starts, page_offset),
                section=section_label,
                parent_text=parent,
            )
        )
    return spans


def build_legal_chunks(
    full_text: str,
    max_chars: int,
    overlap: int = _SENTENCE_OVERLAP,
) -> list[TextSpan]:
    r"""Pecah teks dokumen legal menjadi chunk per Pasal.

    Args:
        full_text: Teks dokumen, halaman digabung dengan pemisah ``\f``.
        max_chars: Batas karakter isi per chunk (header tidak dihitung).
        overlap: Overlap karakter kalau pemecahan jatuh ke batas kalimat.

    Returns:
        Daftar TextSpan terurut sesuai dokumen, atau list kosong kalau teks
        tidak terdeteksi sebagai dokumen legal.
    """
    if max_chars <= 0:
        raise ValueError("max_chars harus lebih besar dari 0")

    # Pemisah halaman dijadikan batas baris supaya heading yang kebetulan
    # menempel di ujung halaman tetap terdeteksi. Normalisasi dijalankan
    # sekali di sini; offset yang dihasilkan merujuk teks ini.
    document = normalize_text(full_text.replace("\f", "\n\f\n"))
    if not document:
        return []

    structure = _parse_structure(document)
    if structure is None:
        return []

    page_starts = _page_starts(document)
    spans: list[TextSpan] = []

    if structure.preamble_end is not None and structure.preamble_end >= _PREAMBLE_MIN_CHARS:
        spans.extend(
            _chunks_for_body(
                header="Pembukaan – Menimbang, Mengingat, dan Menetapkan",
                section_label="Pembukaan",
                body_start=0,
                body_end=structure.preamble_end,
                document=document,
                max_chars=max_chars,
                overlap=overlap,
                page_starts=page_starts,
            )
        )

    for index, pasal in enumerate(structure.pasals):
        body_start = pasal.heading_start + pasal.heading_len + 1
        if index + 1 < len(structure.pasals):
            body_end = structure.pasals[index + 1].heading_start
        elif structure.closing_start is not None and structure.closing_start > body_start:
            body_end = structure.closing_start
        else:
            body_end = len(document)

        if body_end <= body_start:
            continue

        spans.extend(
            _chunks_for_body(
                header=_section_header(pasal),
                section_label=f"Pasal {pasal.nomor}",
                body_start=body_start,
                body_end=body_end,
                document=document,
                max_chars=max_chars,
                overlap=overlap,
                page_starts=page_starts,
                first_page_offset=pasal.heading_start,
            )
        )

    if structure.closing_start is not None:
        closing_text = document[structure.closing_start:].strip()
        if len(closing_text) >= _CLOSING_MIN_CHARS:
            spans.extend(
                _chunks_for_body(
                    header="Penetapan dan Pengundangan",
                    section_label="Penetapan",
                    body_start=structure.closing_start,
                    body_end=len(document),
                    document=document,
                    max_chars=max_chars,
                    overlap=overlap,
                    page_starts=page_starts,
                )
            )

    return spans


def legal_structure_summary(spans: list[TextSpan]) -> str:
    """Ringkasan kecil untuk log: berapa Pasal dan median ukuran chunk."""
    pasal_sections = [
        span for span in spans if span.section and span.section.startswith("Pasal")
    ]
    if not pasal_sections:
        return "tanpa pasal"
    sizes = [len(span.content) for span in pasal_sections]
    return f"{len(pasal_sections)} pasal, median {statistics.median(sizes):.0f} karakter"
