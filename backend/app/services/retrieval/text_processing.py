"""Pemrosesan teks untuk retrieval berbahasa Indonesia.

BM25 hanya bisa menyambung pertanyaan dengan isi dokumen kalau keduanya
melewati tokenisasi yang **sama**. Teks legal Indonesia kaya bentuk turunan:
"pengaduan", "mengadu", dan "diadukan" adalah tiga kata yang bermakna satu,
tapi tanpa stemming ketiganya adalah tiga token berbeda dan pertanyaan yang
memakai salah satunya melewatkan chunk yang memakai dua lainnya.

Stemmer Sastrawi dijalankan dengan cache: mesti-mustahil satu instansi
melayani ribuan kata unik per dokumen, tapi stemmer itu sendiri bekerja
sekitar ratusan mikrodetik per kata dan terasa saat korpus ribuan chunk.
Cache memotong biayanya jadi sekali per kata unik sepanjang umur proses.
"""

from __future__ import annotations

import re

from app.core.config import Settings

#: Token = deretan huruf latin (termasuk diakritik) atau angka.
_TOKEN_RE = re.compile(r"[a-zà-ÿ0-9]+")

#: Stopwords Bahasa Indonesia yang paling sering muncul di dokumen legal.
#: Daftar dibangun dari kata fungsi, bukan kata isi: membuang kata isi
#: (misal "wajib", "pengaduan") berarti membuang sinyal pencarian.
_INDONESIAN_STOPWORDS = frozenset(
    {
        "yang",
        "untuk",
        "dan",
        "atau",
        "di",
        "ke",
        "dari",
        "pada",
        "dalam",
        "dengan",
        "tanpa",
        "adalah",
        "itu",
        "ini",
        "apakah",
        "bagaimana",
        "berapa",
        "siapa",
        "kapan",
        "dimana",
        "kenapa",
        "mengapa",
        "apa",
        "bila",
        "jika",
        "kalau",
        "sebagaimana",
        "sebagaiman",
        "tentang",
        "terhadap",
        "atas",
        "oleh",
        "akan",
        "telah",
        "sudah",
        "sedang",
        "dapat",
        "bisa",
        "harus",
        "mau",
        "ingin",
        "ada",
        "tidak",
        "bukan",
        "juga",
        "saja",
        "lebih",
        "paling",
        "antara",
        "sampai",
        "sejak",
        "karena",
        "sehingga",
        "yaitu",
        "yakni",
        "sebuah",
        "para",
        "kami",
        "kita",
        "saya",
        "anda",
        "mereka",
        "dia",
        "ia",
        "nya",
        "ataupun",
        "maupun",
        "tetapi",
        "namun",
        "sehinggakan",
        "boleh",
        "setiap",
        "seluruh",
        "semua",
        "bagian",
        "hal",
        "contoh",
        "misal",
        "misalnya",
    }
)

#: Stopwords Inggris yang mungkin muncul di dokumen campuran.
_ENGLISH_STOPWORDS = frozenset(
    {
        "the",
        "a",
        "an",
        "of",
        "to",
        "in",
        "on",
        "for",
        "with",
        "and",
        "or",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "what",
        "how",
        "when",
        "where",
        "who",
        "which",
        "that",
        "this",
        "these",
        "those",
        "it",
        "as",
        "by",
        "at",
        "from",
    }
)

_STOPWORDS = _INDONESIAN_STOPWORDS | _ENGLISH_STOPWORDS

#: Batas cache stemming. Stemmer menghasilkan bentuk dasar yang stabil, jadi
#: melewati batas ini berarti korpusnya benar-benar berubah; entri lama boleh
#: dikorbankan.
_STEM_CACHE_MAX = 100_000

_stemmer = None
_stem_cache: dict[str, str] = {}
_stemming_active = False


def _get_stemmer():  # noqa: ANN202
    """Muat stemmer Sastrawi sekali, malas (lazy).

    Pemuatan malas bukan gaya-gayaan: mengimpor Sastrawi membangun kamus
    aksara (~100 ribu aturan) dan itu tidak boleh dibayar saat modul diimpor
    di jalur yang tidak memakai stemming sama sekali (test stub, mode tanpa
    stemming).
    """
    global _stemmer
    if _stemmer is None:
        try:
            from Sastrawi.Stemmer.StemmerFactory import StemmerFactory
        except ImportError:
            # Stemmer tidak terpasang: stemming dinonaktifkan dengan aman,
            # tokenisasi tetap jalan tanpa stemming.
            return None
        _stemmer = StemmerFactory().create_stemmer()
    return _stemmer


def stem_word(word: str) -> str:
    """Bentuk dasar satu kata, dengan cache proses-level."""
    if not _stemming_active:
        return word
    cached = _stem_cache.get(word)
    if cached is not None:
        return cached
    stemmer = _get_stemmer()
    stemmed = stemmer.stem(word) if stemmer is not None else word
    if len(_stem_cache) < _STEM_CACHE_MAX:
        _stem_cache[word] = stemmed
    return stemmed


def configure_stemming(settings: Settings) -> None:
    """Nyalakan/matikan stemming sesuai konfigurasi.

    Dipanggil saat retriever dibangun. Tokenisasi dokumen dan query harus
    memakai konfigurasi yang sama — kalau keduanya berbeda, BM25 membandingkan
    dua kosakata yang tidak bertemu.
    """
    global _stemming_active
    _stemming_active = settings.bm25_stemming_enabled


def tokenize_for_search(text: str) -> list[str]:
    """Token untuk BM25: huruf kecil, tanpa stopwords, bentuk dasar Sastrawi.

    Angka dipertahankan apa adanya ("60", "2013" adalah sinyal kuat di
    dokumen legal) dan tidak di-stem. Kata satu huruf dibuang karena nyaris
    selalu sisa potongan kata, bukan isi.
    """
    tokens: list[str] = []
    for raw in _TOKEN_RE.findall(text.lower()):
        if raw.isdigit():
            tokens.append(raw)
            continue
        if len(raw) <= 1 or raw in _STOPWORDS:
            continue
        tokens.append(stem_word(raw))
    return tokens


def keyword_suggestions(question: str, limit: int = 6) -> tuple[str, ...]:
    """Kata kunci dari pertanyaan, untuk saran saat tidak ada hasil.

    Dipanggil ketika retrieval kosong: pengguna diberi istilah yang benar-benar
    ada peluangnya di dokumen, bukan ditolak dengan kalimat kosong. Tanpa
    cache sengaja: pertanyaan pengguna unik, dan komputasinya sendiri hanya
    regex sekali jalan.
    """
    words = [
        raw
        for raw in _TOKEN_RE.findall(question.lower())
        if not raw.isdigit() and len(raw) > 1 and raw not in _STOPWORDS
    ]
    # Dedupe dengan dict.fromkeys (menjaga urutan kemunculan), slice setelah
    # jadi list.
    unique = list(dict.fromkeys(words))
    return tuple(unique[:limit])
