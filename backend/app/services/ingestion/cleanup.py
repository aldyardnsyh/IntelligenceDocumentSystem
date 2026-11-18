"""Pembersihan teks hasil ekstraksi PDF.

Aturannya sengaja konservatif. Yang dibuang hanya pola yang nyata-nyata
artefak halaman — nomor halaman, cap "PRESIDEN REPUBLIK INDONESIA" di kaki
halaman, dan baris lanjutan ber-"..." milik penanda halaman — bukan "kata
yang tampak salah". Memperbaiki kata secara buta berbahaya: "Undang-Undan g"
memang bisa disambung, tapi aturan yang sama merusak kata sah seperti "ke"
menjadi bagian kata sebelumnya. Perbaikan teks yang benar-benar rusak bukan
tugas regex — itu tugas jalur vision OCR yang membaca citra halaman.

Pengecualian satu-satunya: **word-fusion** (beberapa kata yang meleleh menjadi
satu token tanpa spasi, mis. "pengadukepadapengelolapengaduanpelayananpublik").
Kasus ini khas pada PDF hasil pindai Lembaran Negara di mana spasi antar kata
hilang setelah pemindaian. Pemisahannya HANYA dilakukan bila seluruh hasil
pecahan adalah kata sah dari kamus legal Indonesia terbatas — bukan pemisahan
buta, sehingga kata sah seperti "berpengaduan" TIDAK akan dipotong.

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

    Urutannya: normalisasi unicode, buang baris noise, pecahkan kata yang
    meleleh (word-fusion), lalu rapikan whitespace. Normalisasi NFKC wajib
    lebih dulu: PP-OCR terlatih pada korpus CJK sering mengeluarkan tanda
    kurung/dash fullwidth ("（1）" untuk "(1)"), dan itu merusak regex
    ayat/butir maupun pencarian "ayat (3)".
    """
    cleaned = unicodedata.normalize("NFKC", text)
    cleaned = strip_noise_lines(cleaned)
    cleaned = split_fused_words(cleaned)
    cleaned = re.sub(r"[ \t]+", " ", cleaned)
    cleaned = re.sub(r" *\n *", "\n", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


#: Kosakata legal Indonesia yang khas muncul pada dokumen pelayanan publik dan
#: peraturan perundang-undangan. Kamus ini TERBATAS: kata di luar daftarnya
#: tidak dipecah (kembali ke dokstring: "yang tampak salah" tidak diutak-atik).
#: Kata-kata di sini dipilih dari frekuensi tinggi pada Perpres/Lembaran Negara
#: yang membahas pengelolaan pengaduan, supaya word-fusion khas dokumen semacam
#: itu ("pengadukepadapengelolapengaduanpelayananpublik") bisa dipulihkan.
_LEXICON: frozenset[str] = frozenset(
    {
        # Kata tugas sangat frekuwen — tanpa ini, pecahan sering gagal karena
        # satu kata tugas di tengah fusion tidak dikenali.
        "yang", "di", "ke", "dari", "pada", "oleh", "untuk", "dengan", "tanpa",
        "dalam", "atas", "bila", "jika", "maka", "karena", "sebagai", "agar",
        "para", "per", "setiap", "seluruh", "selama", "sejak", "sampai",
        "tidak", "bukan", "ada", "bisa", "dapat", "akan", "sudah", "belum",
        "harus", "wajib", "boleh", "mungkin", "paling", "lebih", "kurang",
        "dan", "atau", "serta", "antara", "terhadap", "tentang", "bagi",
        "ini", "itu", "tersebut", "sebut", "demikian", "begitu",
        # Subjek/objek legal pelayanan publik.
        "peraturan", "presiden", "republik", "indonesia", "negara", "lembaran",
        "tahun", "nomor", "pasal", "ayat", "huruf", "angka", "butir", "bab",
        "bagian", "paragraf", "klausul", "undang", "ketentuan",
        "disempurnakan", "diubah", "ditetapkan", "diundangkan",
        # Domain pengaduan.
        "pengaduan", "pengadu", "pengelola", "pengelolaan",
        "penyelenggara", "penyelenggaraan",
        "pelayanan", "layanan", "publik", "keluhan", "keluh", "penyampaian",
        "sarana", "masyarakat", "pelaporan", "pencatatan", "penanganan",
        "penyelesaian", "penelaahan", "pengklasifikasian", "penyaluran",
        "pemantauan", "evaluasi", "pengumuman", "sosialisasi", "penerimaan",
        "penugasan", "kewenangan", "keberatan", "pelanggaran", "pengabaian",
        "kewajiban", "larangan", "perlindungan", "kerahasiaan", "penjelasan",
        "kualitas", "standar", "petugas", "pejabat",
        "pegawai", "organisasi", "institusi", "lembaga", "korporasi",
        # Kata kerja umum pada bahasa peraturan.
        "melakukan", "memberikan", "menyampaikan", "diterima", "disampaikan",
        "diselesaikan", "ditanggapi", "diproses", "ditindaklanjuti", "diarsip",
        "diarsipkan", "dikoordinasikan", "mengumumkan", "menyusun", "membuat",
        "bertugas", "melaksanakan", "disebut", "berada", "mewakili", "mewakilinya",
        "mendirikan", "menjalankan", "memperhatikan", "mempertimbangkan",
        "mengelola", "mengatur", "mengerjakan", "menyediakan",
        "disediakan", "ditugaskan", "dibentuk", "dibentukkan", "membentuk",
        "berwenang", "bertanggungjawab", "bertanggung", "jawab", "bertujuan",
        "berkaitan", "berhubungan", "berdasarkan", "dimaksud", "dimaksudkan",
        "tertentu", "tersedia", "memenuhi", "dipenuhi", "memuat",
        # Adjektiva dan kata benda turunan yang umum.
        "adalah", "perlu",
        "penting", "utama", "kedua", "pertama", "ketiga", "beberapa",
        "semua", "banyak", "sedikit", "cukup", "sama", "berbeda", "lain",
        # Kata lain yang sering menempel di corpus legal.
        "tanggal", "bulan", "hari", "jam", "menit", "waktu", "batas", "jangka",
        "biaya", "upah", "imbalan", "fasilitas", "kegiatan", "tindakan",
        "keputusan", "kebijakan", "ketua", "anggota", "pengurus", "pimpinan",
    }
)

#: Panjang minimum fusion yang dicoba dipecahkan: di bawah ini, kata sah
#: Indonesia (termasuk "mengizinkan", "menyelenggarakan") bisa tercapai dan
#: tidak ada manfaat mengambil risiko salah potong.
_FUSION_MIN_LEN = 18

#: Batas jumlah kata "asing" (tidak ada di kamus) yang masih diterima dalam
#: satu solusi pemecahan. Nilai 1 membolehkan satu nama/singkatan tak dikenal
#: (mis. "bistoksimbolon") di antara kata-kata kamus, tanpa membiarkan solusi
#: liar di mana separuh pecahannya adalah karangan.
_FUSION_MAX_UNKNOWN = 1

#: Panjang minimum pecahan yang TIDAK ada di kamus. Pecahan lebih pendek dari
#: ini hanya sah bila memang anggota kamus ("di", "ke", "dan"). Mencegah
#: fragmen 1-2 huruf tak dikenal memenangkan tiebreak "lebih banyak kata".
_FUSION_MIN_PIECE_LEN = 3


_BEST = tuple[int, int, list[int]] | None


def _segment_fusion(token: str) -> list[str] | None:
    """Pecahkan satu token jadi kata-kata kamus bila solusinya meyakinkan.

    Algoritma: pemrograman dinamis yang mencari pemecahan dengan jumlah kata
    tak dikenal paling sedikit, dipecah dari pemilihan pecahan terpanjang
    terlebih dahulu (greedy longest match). Mengembalikan ``None`` kalau solusi
    terbaiknya masih memuat lebih dari ``_FUSION_MAX_UNKNOWN`` kata yang tidak
    ada di kamus — itu berarti token ini kemungkinan bukan word-fusion, dan
    membiarkan apa adanya lebih aman daripada menebak.

    Batas tambahan: pecahan yang BUKAN anggota kamus harus panjangnya >= 3
    huruf. Tanpa ini, pecahan pendek tak dikenal (mis. "an") bisa lolos dan,
    lewat tiebreak "lebih banyak kata lebih baik", mengalahkan solusi yang
    mempertahankan kata sah panjang ("pengelolaan" terbelah jadi "pengelola an").
    """
    length = len(token)
    # cost[i] = (jumlah kata tak dikenal, minus panjang rata-rata pecahan)
    # tuple (unknown_count, negatif_total_kata) supaya tie dipecah oleh
    # jumlah kata: makin banyak kata berarti pecahan lebih halus.
    best: list[_BEST] = [None] * (length + 1)
    best[length] = (0, 0, [])

    for start in range(length - 1, -1, -1):
        for end in range(start + 1, length + 1):
            rest = best[end]
            if rest is None:
                continue
            piece = token[start:end]
            # Pecahan di luar kamus wajib cukup panjang — fragmen 1-2 huruf
            # ("an", "ke", "la") nyaris pasti bukan kata, hanya sisa potongan
            # salah dari pecahan sah yang seharusnya utuh. Kata tugas pendek
            # sah tetap boleh karena ada di kamus ("di", "ke", "dan").
            if piece in _LEXICON:
                unknown = 0
            elif len(piece) < _FUSION_MIN_PIECE_LEN:
                continue
            else:
                unknown = 1
            candidate_unknown = rest[0] + unknown
            if candidate_unknown > _FUSION_MAX_UNKNOWN:
                continue
            candidate_neg_words = rest[1] - 1
            candidate = (candidate_unknown, candidate_neg_words, [start, *rest[2]])
            current = best[start]
            if current is None or candidate[:2] < current[:2]:
                best[start] = candidate

    head = best[0]
    if head is None or head[0] > _FUSION_MAX_UNKNOWN:
        return None
    boundaries = head[2]
    # boundaries hanya menyimpan START tiap pecahan; ujung kanan pecahan
    # terakhir = panjang token itu sendiri. Tanpa menambah length di sini,
    # pecahan terakhir selalu terbuang oleh range(len-1) di bawah.
    return [
        token[boundaries[i]:boundaries[i + 1]]
        for i in range(len(boundaries) - 1)
    ] + [token[boundaries[-1]:length]]


#: Token yang layak dicoba dipecah: alfabet kecil murni, tanpa digit, tanpa
#: tanda hubung, dan cukup panjang untuk berpotensi jadi word-fusion.
_FUSION_TOKEN_RE = re.compile(r"[A-Za-z]{" f"{_FUSION_MIN_LEN},}}")


def split_fused_words(text: str) -> str:
    """Sisipkan spasi pada word-fusion OCR yang bisa dipecahkan dengan yakin.

    Kata-kata di luar kamus (atau token pendek, atau token yang mengandung
    digit/tanda baca) dibiarkan apa adanya. Fungsi ini sengaja TIDAK mencoba
    menebak kata yang "hampir benar": itu ranah jalur vision.
    """
    if not text:
        return text

    def _replace(match: re.Match[str]) -> str:
        token = match.group(0)
        split = _segment_fusion(token)
        return " ".join(split) if split else token

    return _FUSION_TOKEN_RE.sub(_replace, text)
