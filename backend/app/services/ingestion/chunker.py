"""Pemecah teks menjadi chunk.

Keputusan chunking adalah salah satu tuning paling berpengaruh di RAG, dan
tidak ada jawaban universal:

- Chunk terlalu besar: banyak noise ikut masuk konteks, token terbuang, dan
  model mudah kehilangan fokus di tengah teks.
- Chunk terlalu kecil: kalimat melintasi batas terpotong, makna hilang.
- Overlap terlalu besar: konteks terisi ulang teks yang sama, boros.
- Overlap terlalu kecil: kalimat penting bisa terpotong tepat di batas.

Strategi di sini: potong di batas paragraf kalau memungkinkan, dan hanya
memotong di tengah karakter kalau paragrafnya sendiri sudah melebihi batas.
Dengan begitu batas chunk hampir selalu jatuh di tempat yang secara semantik
wajar.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass

#: Pola heading Markdown, dipakai sebagai batas struktur dokumen.
_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s+\S")
#: Kalimat diakhiri tanda baca yang lazim di teks Indonesia.
_SENTENCE_END_RE = re.compile(r"(?<=[.!?])\s+")


@dataclass(slots=True)
class TextSpan:
    """Potongan teks dengan posisi karakter aslinya."""

    content: str
    char_start: int
    char_end: int
    page_number: int | None = None

    def token_estimate(self) -> int:
        """Perkiraan jumlah token.

        Kasar: satu token kira-kira empat karakter untuk teks Indonesia
        dan Inggris. Hanya dipakai untuk ditampilkan, bukan untuk slicing.
        """
        return max(1, round(len(self.content) / 4))


def normalize_text(text: str) -> str:
    """Bersihkan teks sebelum dipecah.

    Menghapus carriage return yang tidak konsisten, merapikan spasi berlebih,
    dan membuang baris kosong bertumpuk. Ekstraksi PDF sering menghasilkan
    spasi dalam jumlah tak terbatas di sekeliling teks.
    """
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    # Spasi berulang jadi satu, tapi newline dipertahankan.
    text = re.sub(r"[ \t ]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    # Tiga newline beruntun jadi dua, supaya batas paragraf tetap terbaca.
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _paragraphs(text: str) -> Iterator[tuple[str, int]]:
    """Hasilkan paragraf beserta posisi awal karakternya.

    Offset harus menunjuk ke teks **yang sudah dinormalisasi**, karena itulah
    teks yang dipecah.

    Posisi dihitung langsung dari pemecahan, bukan dari ``str.find`` dengan
    cursor tebakan. Versi sebelumnya memajukan cursor dua kali (sekali di
    dalam ``if``, sekali lagi setelahnya), sehingga offset meleset jauh dan
    pada dokumen pendek bahkan menunjuk melewati ujung teks. Akibatnya
    Citation Card menyorot potongan yang salah, dan sumber yang ditampilkan
    tidak cocok dengan isinya.
    """
    position = 0
    for block in text.split("\n\n"):
        stripped = block.strip()
        if stripped:
            # Jarak dari awal blok ke teks yang sudah di-strip.
            lead = len(block) - len(block.lstrip())
            yield stripped, position + lead
        # maju melewati seluruh blok termasuk pemisah "\n\n"
        position += len(block) + 2


def _split_long_paragraph(
    paragraph: str,
    start: int,
    size: int,
    overlap: int,
) -> Iterator[TextSpan]:
    """Potong paragraf yang lebih panjang dari ``size`` di batas kalimat.

    Pemotongan karakter dari tengah kata menghasilkan potongan yang sulit
    dibaca dan membingungkan pembaca chunk, jadi batas kalimat diprioritaskan.
    """
    if len(paragraph) <= size:
        yield TextSpan(content=paragraph, char_start=start, char_end=start + len(paragraph))
        return

    sentences = _SENTENCE_END_RE.split(paragraph)
    buffer = ""
    buffer_start = start

    for sentence in sentences:
        if not sentence:
            continue
        candidate = f"{buffer} {sentence}".strip() if buffer else sentence
        if len(candidate) <= size:
            buffer = candidate
            continue

        if buffer:
            yield TextSpan(
                content=buffer,
                char_start=buffer_start,
                char_end=buffer_start + len(buffer),
            )
            # Carry ekor kalimat sebelumnya supaya kalimat yang melintasi batas
            # tidak hilang utuh di chunk berikutnya.
            carry = buffer[-overlap:] if overlap > 0 else ""
            buffer = f"{carry} {sentence}".strip()
            buffer_start = start + len(paragraph) - len(buffer)
        else:
            # Satu kalimat lebih panjang dari size: harus dipotong karakter.
            for index in range(0, len(sentence), size - overlap):
                piece = sentence[index : index + size]
                if not piece.strip():
                    continue
                piece_start = start + index
                yield TextSpan(
                    content=piece.strip(),
                    char_start=piece_start,
                    char_end=piece_start + len(piece.strip()),
                )

    if buffer.strip():
        yield TextSpan(
            content=buffer.strip(),
            char_start=buffer_start,
            char_end=buffer_start + len(buffer.strip()),
        )


def chunk_text(
    text: str,
    size: int,
    overlap: int,
    page_number: int | None = None,
) -> list[TextSpan]:
    """Pecah teks menjadi chunk.

    Args:
        text: Teks dokumen, mentah atau sudah dinormalisasi.
        size: Batas panjang chunk dalam karakter.
        overlap: Berapa karakter ekor yang dibawa ke chunk berikutnya.
        page_number: Nomor halaman, diteruskan ke setiap chunk.

    Returns:
        Daftar TextSpan terurut sesuai kemunculan di dokumen.
    """
    if size <= 0:
        raise ValueError("size harus lebih besar dari 0")
    if overlap < 0 or overlap >= size:
        raise ValueError("overlap harus di antara 0 dan size")

    normalized = normalize_text(text)
    if not normalized:
        return []

    spans: list[TextSpan] = []
    for paragraph, start in _paragraphs(normalized):
        if _HEADING_RE.match(paragraph):
            # Heading selalu jadi awal chunk sendiri supaya konteksnya utuh
            # dan tidak menempel ke paragraf sebelumnya.
            spans.append(
                TextSpan(
                    content=paragraph,
                    char_start=start,
                    char_end=start + len(paragraph),
                    page_number=page_number,
                )
            )
            continue
        for span in _split_long_paragraph(paragraph, start, size, overlap):
            spans.append(
                TextSpan(
                    content=span.content,
                    char_start=span.char_start,
                    char_end=span.char_end,
                    page_number=page_number,
                )
            )

    return spans
