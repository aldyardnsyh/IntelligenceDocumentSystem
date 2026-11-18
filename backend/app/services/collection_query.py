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

Modul ini juga mendeteksi sapaan kecil (``is_smalltalk``): pertanyaan yang
bukan tentang dokumen sama sekali, sehingga pipeline dokumen tidak perlu
disentuh untuk menjawabnya.
"""

from __future__ import annotations

import re

#: Pola pertanyaan meta: pengguna bertanya TENTANG dokumennya sendiri, bukan
#: tentang detail di dalamnya. Contoh: "ini dokumen terkait dengan apa?",
#: "dokumen ini dari mana?", "ini peraturan apa?", "apa isi pokok dokumen ini?".
#:
#: Kenapa perlu jalur terpisah: pertanyaan meta tidak menunjuk pasal atau
#: istilah spesifik, jadi retrieval normal memberi skor rendah dan jatuh ke
#: "tidak ditemukan". Padahal dokumennya ada dan pengguna hanya butuh
#: gambaran umum.
#:
#: Konservatif: hanya frasa eksplisit yang mengarahkan ke "dokumen ini apa".
#: Dihindari salah tangkap pertanyaan substantif ("tentang pelayanan publik apa
#: syaratnya" ≠ meta). Kombinasi penanda dokumen + pengarah tanya sangat
#: spesifik terhadap maksud meta.
_META_PATTERNS = (
    re.compile(
        r"\b(dokumen|berkas|file)\b.{0,30}\b"
        r"(terkait dengan apa|tentang apa|dari mana|apa ini|ini apa)\b"
    ),
    re.compile(r"\b(dokumen|berkas|file)\b.{0,20}\bini\b.{0,20}\b(apa|dari mana)\b"),
    re.compile(
        r"\bini\b.{0,15}\b(dokumen|berkas|file)\b.{0,20}\b(apa|tentang apa|dari mana)\b"
    ),
    # Wajib frasa "dokumen/berkas/file ini" berdampingan, bukan sekadar
    # "apa ... dokumen ... ini" yang luas. Tanpa ini, "apa isi dokumen ini?"
    # (pertanyaan isi generik) ikut tersangkap dan salah dialihkan ke overview.
    re.compile(
        r"\b(dokumen|berkas|file)\s+(ini|itu|tersebut)\b.{0,15}\bapa\b"
    ),
    re.compile(r"\bapa\b.{0,4}\b(dokumen|berkas|file)\s+(ini|itu|tersebut)\b"),
    # "dari mana dokumen ini" (urutan terbalik dari "dokumen ini dari mana").
    re.compile(r"\bdari mana\b.{0,15}\b(dokumen|berkas|file)\s*(ini|itu|tersebut)?\b"),
    re.compile(
        r"\b(dokumen|berkas|file)\b.{0,10}\bini\b.{0,20}"
        r"\b(peraturan|regulasi|standar|prosedur|sop)\b.{0,10}\b(apa|mana)\b"
    ),
    # "isi pokok" + kata jenis dokumen, ATAU "dokumen ini/itu" + "isi pokok".
    # Tidak menangkap "apa isi dokumen ini?" (pertanyaan isi generik, jalur
    # retrieval normal) karena tidak ada kata jenis di sana.
    re.compile(
        r"\b(isi pokok|pokok isi)\b.{0,20}"
        r"\b(peraturan|regulasi|standar|sop|prosedur|panduan)\b"
    ),
    re.compile(
        r"\b(dokumen|berkas|file)\b.{0,5}\b"
        r"(ini|itu|tersebut)\b.{0,10}\b(isi pokok|pokok isi)\b"
    ),
    # "apa isi dokumen peraturan ini" meta; TAPI "apa isi dokumen ini" tidak
    # (pertanyaan isi generik). Kuncinya: harus ada kata jenis dokumen.
    re.compile(
        r"\bapa\b.{0,6}\b(isi|pokok)\b.{0,12}\b"
        r"(peraturan|regulasi|standar|sop|prosedur|panduan)\b"
    ),
    re.compile(r"\bmembahas\b.{0,15}\b(apa|tentang apa)\b.{0,15}\b(dokumen|berkas|file)\b"),
    re.compile(r"\bapa yang dibahas\b.{0,20}\b(dokumen|berkas|file)\b"),
    re.compile(r"\b(dokumen|berkas|file)\b.{0,15}\bini\b.{0,20}\bberisi apa\b"),
    re.compile(r"\bgambaran umum\b.{0,30}\b(dokumen|berkas|file)\b"),
)

#: Meta question perlu setidaknya ada sinyal "dokumen aktif" atau "ini" di
#: pertanyaannya supaya benar-benar meta. Kata "dokumen" saja + frasa meta
#: sudah cukup. Mencegah salah tangkap pertanyaan isi generik.
_META_STRENGTH_MARKER = re.compile(r"\b(dokumen|berkas|file|ini)\b")


def is_meta_question(question: str) -> bool:
    """True kalau pertanyaan meta: tentang dokumennya sendiri, bukan isinya.

    Contoh yang terdeteksi:
    - "Ini dokumen terkait dengan apa?"
    - "Dokumen ini tentang apa?"
    - "Ini dokumen apa sih?"
    - "Dokumen ini dari mana?"
    - "Apa isi pokok dokumen ini?"
    - "Dokumen ini adalah peraturan apa?"

    Contoh yang TIDAK terdeteksi (pertanyaan substantif, biarkan ke retrieval):
    - "Tentang pelayanan publik apa syarat pengajuan?"
    - "Bagaimana cara mengajukan permohonan?"
    - "Apa yang dimaksud dengan pengaduan?"
    """
    text = question.strip().lower()
    if not text:
        return False

    # Harus ada pola meta + ada kata yang menunjuk "dokumen ini".
    if not any(pattern.search(text) for pattern in _META_PATTERNS):
        return False
    if not _META_STRENGTH_MARKER.search(text):
        return False

    # Bukan meta kalau pertanyaannya substantive (minta proses/syarat/durasi).
    substantive_markers = (
        "cara mengajukan",
        "berapa lama",
        "berapa hari",
        "berapa sls",
        "biaya",
        "syarat pengajuan",
        "prosedyur mengajukan",
        "alur proses",
    )
    return not any(marker in text for marker in substantive_markers)


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


#: Batas panjang pertanyaan yang masih dianggap sapaan. Pertanyaan isi
#: dokumen bisa saja dibuka "halo", tapi pertanyaan yang layak dijawab dari
#: dokumen hampir selalu lebih panjang dari ini.
_MAX_SMALLTALK_LEN = 90

#: Sapaan dan ucapan terima kasih. Dicocokkan di AWAL pertanyaan saja:
#: "halo" di depan adalah sapaan, "informasi halal" bukan.
_GREETING_PREFIX = re.compile(
    r"^(halo|hai|hi|hello|hey|hallo|selamat\s+(pagi|siang|sore|malam)"
    r"|assalamualaikum|salam|terima\s*kasih|makasih|makasi|thanks|thank\s+you)\b",
    re.IGNORECASE,
)

#: Pertanyaan tentang identitas dan kemampuan aplikasi. Ini tidak bisa
#: dijawab dari dokumen mana pun, jadi jalannya beda dari pertanyaan isi.
_CAPABILITY_PATTERNS = (
    re.compile(r"\b(?:siapa|siapakah)\s+(?:kamu|anda|kalian)\b"),
    re.compile(r"\b(?:kamu|anda)\s+siapa\b"),
    re.compile(r"\bapa\s+(?:kamu|anda)\b"),
    re.compile(r"\b(?:kamu|anda)\s+bisa\b"),
    re.compile(r"\bapa\s+(?:yang\s+)?bisa\s+(?:kamu|anda|lo)\b"),
    re.compile(r"\bkemampuan\s+(?:kamu|anda)\b"),
    re.compile(r"\bcara\s+(?:pakai|memakai|gunakan|menggunakan)\b"),
    re.compile(r"\bbantu\s+apa\b"),
    re.compile(r"\bbisa\s+bantu\b"),
)


def is_smalltalk(question: str) -> bool:
    """True kalau pertanyaannya sapaan atau tanya kemampuan, bukan isi dokumen.

    Pengguna demo hampir selalu menyapa dulu: "halo", "kamu bisa apa?",
    "terima kasih". Menyambut sapaan itu dengan penolakan robotik "tidak
    ditemukan dalam dokumen" adalah blunder presentasi yang paling mudah
    dicegah. Pertanyaan seperti ini tidak ada di dokumen mana pun, jadi
    embedding dan retrieval tidak punya apa-apa untuk dikerjakan; lebih baik
    dijawab hangat langsung tanpa menyentuh pipeline dokumen.

    Pencocokan sengaja konservatif:

    - Sapaan hanya dihitung kalau berada di AWAL pertanyaan. Kata yang
      kebetulan memuat huruf yang sama di tengah kalimat bukan sapaan.
    - Pertanyaan lebih panjang dari ``_MAX_SMALLTALK_LEN`` tidak pernah
      dianggap sapaan, berapa pun kata sapaan yang muncul di depannya:
      pertanyaan isi yang serius hampir selalu lebih panjang.
    """
    text = question.strip()
    if not text or len(text) > _MAX_SMALLTALK_LEN:
        return False
    lowered = text.lower()
    if _GREETING_PREFIX.match(lowered):
        return True
    return any(pattern.search(lowered) for pattern in _CAPABILITY_PATTERNS)


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
