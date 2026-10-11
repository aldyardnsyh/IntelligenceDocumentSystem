"""Deteksi pertanyaan tentang koleksi dokumen, bukan tentang isinya.

Pengguna yang bertanya "carikan dokumen terkait tiketing" sedang bertanya
tentang **koleksi**, bukan tentang isi satu dokumen. Menjawabnya dari
pengetahuan umum menghasilkan halusinasi paling berbahaya: daftar buku dengan
penulis, tahun, dan URL yang tidak ada, terlihat kredibel, dan tidak bisa
dicek.

Yang benar: jawab dari daftar dokumen yang benar-benar tersimpan.

Modul ini sengaja sederhana dan bisa diuji: pola kata kunci, bukan model.
Deteksi yang salah tebak hanya mengubah cara menjawab, bukan isi jawaban,
jadi risikonya kecil. Sebaliknya, melewatkan deteksi berarti halusinasi
referensi lolos.
"""

from __future__ import annotations

import re

#: Kata yang menandakan pertanyaan tentang daftar dokumen, bukan isinya.
_COLLECTION_PATTERNS = (
    re.compile(r"\b(cari|carikan|temukan|cariin|ada|punya)\b.{0,30}\b(dokumen|berkas|file)\b"),
    re.compile(r"\b(dokumen|berkas|file)\b.{0,30}\b(apa saja|apa aja|tersedia|yang ada)\b"),
    re.compile(r"\b(daftar|list)\b.{0,20}\b(dokumen|berkas|file)\b"),
    re.compile(r"\bberapa\b.{0,20}\b(dokumen|berkas|file)\b"),
    re.compile(r"\b(dokumen|berkas|file)\b.{0,25}\b(tentang|terkait|mengenai|soal)\b"),
    re.compile(r"\b(tentang|terkait|mengenai)\b.{0,25}\b(tiketing|tiket)\b.{0,20}\b(dokumen|berkas)\b"),
)

#: Kata yang menandakan pertanyaan tentang isi, bukan tentang koleksi.
#: "apa isi dokumen tiketing?" tetap pertanyaan isi.
_CONTENT_MARKERS = (
    "isi",
    "jelaskan",
    "ringkas",
    "rangkum",
    "sebutkan",
    "bagaimana",
    "kenapa",
    "mengapa",
    "berapa hari",
    "berapa lama",
    "berapa biaya",
)


def is_collection_question(question: str) -> bool:
    """True kalau pertanyaannya tentang dokumen apa saja yang tersedia.

    Contoh yang terdeteksi:
    - "carikan dokumen terkait tiketing"
    - "dokumen apa saja yang tersedia?"
    - "ada berapa dokumen?"
    - "dokumen tentang tiket"

    Contoh yang TIDAK terdeteksi (dan memang tidak boleh):
    - "apa isi dokumen tiketing?" (pertanyaan isi)
    - "berapa hari SLA penyelesaian?" (pertanyaan isi)
    """
    text = question.strip().lower()
    if not text:
        return False
    if not any(pattern.search(text) for pattern in _COLLECTION_PATTERNS):
        return False
    # Kalau ada penanda pertanyaan isi yang jelas, itu pertanyaan isi.
    return not any(marker in text for marker in _CONTENT_MARKERS)


#: Kata umum yang dibuang saat mencocokkan topik ke nama dokumen.
_STOPWORDS = {
    "cari",
    "carikan",
    "cariin",
    "temukan",
    "dokumen",
    "berkas",
    "file",
    "tentang",
    "terkait",
    "mengenai",
    "soal",
    "yang",
    "ada",
    "apa",
    "saja",
    "aja",
    "tersedia",
    "daftar",
    "list",
    "berapa",
    "dan",
    "atau",
    "untuk",
    "dengan",
    "di",
    "ke",
    "dari",
    "ini",
    "itu",
    "saya",
    "punya",
    "tolong",
}


def topic_terms(question: str) -> list[str]:
    """Kata kunci topik dari pertanyaan koleksi.

    Dipakai untuk menyaring dokumen mana yang relevan dengan topik yang
    disebut pengguna ("tiketing" pada "carikan dokumen terkait tiketing").
    """
    words = re.findall(r"[a-z0-9]+", question.lower())
    return [word for word in words if word not in _STOPWORDS and len(word) > 2]


#: Panjang awalan yang dianggap cukup untuk menyatakan dua kata seakar.
#: "tiketing" dan "tiket" berbagi empat huruf pertama, jadi keduanya cocok.
_STEM_PREFIX = 4


def _stem(word: str) -> str:
    """Awalan kata untuk pencocokan kasar.

    Bahasa Indonesia banyak berimbuhan ("tiket" jadi "tiketing", "berkas"
    jadi "berkasan"), dan tanpa library stemming, membandingkan awalan sudah
    cukup untuk mencocokkan nama berkas. Ini bukan analisis morfologi, dan
    memang tidak perlu: hasilnya hanya memilih dokumen mana yang disebut di
    jawaban.
    """
    return word[:_STEM_PREFIX]


def matches_topic(filename: str, terms: list[str]) -> bool:
    """True kalau nama berkas cocok dengan salah satu kata kunci topik.

    Pencocokan dilakukan pada awalan kata, bukan substring penuh, supaya
    "tiketing" menemukan "panduan-tiket-layanan.md". Tanpa ini, pengguna
    menulis bentuk berimbuhan dan dokumen yang jelas relevan justru
    dilaporkan tidak ada.
    """
    name_words = re.findall(r"[a-z0-9]+", filename.lower())
    name_stems = {_stem(word) for word in name_words if len(word) >= _STEM_PREFIX}
    for term in terms:
        if len(term) < _STEM_PREFIX:
            # Kata pendek dibandingkan apa adanya supaya tidak mencocokkan
            # terlalu banyak.
            if term in name_words:
                return True
            continue
        if _stem(term) in name_stems:
            return True
    return False
