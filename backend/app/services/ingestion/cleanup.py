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


#: Peta tanda baca varian yang tidak diratakan NFKC. NFKC menormalkan bentuk
#: kompatibel (fullwidth, ligature) tapi membiarkan karakter yang hanya
#: berbeda "gaya tipografi": kutipan keriting, dash panjang, ellipsis satu
#: karakter. Semuanya sah secara unicode, jadi pembersihan ini bukan koreksi
#: kata — hanya menyamakan tanda baca ke bentuk ASCII yang dipakai regex
#: ayat/butir, pencarian, dan penandaan sitasi.
_SYMBOL_MAP = str.maketrans(
    {
        "\u2018": "'",  # ' left single quote
        "\u2019": "'",  # ' right single quote
        "\u201a": "'",  # ‚ single low quote
        "\u201b": "'",  # ' single high-reversed
        "\u2032": "'",  # ′ prime
        "\u201c": '"',  # " left double quote
        "\u201d": '"',  # " right double quote
        "\u201e": '"',  # „ double low quote
        "\u201f": '"',  # " double high-reversed
        "\u2033": '"',  # ″ double prime
        "\u2010": "-",  # ‐ hyphen
        "\u2011": "-",  # ‑ non-breaking hyphen
        "\u2012": "-",  # ‒ figure dash
        "\u2013": "-",  # – en dash
        "\u2014": "-",  # — em dash
        "\u2015": "-",  # ― horizontal bar
        "\u2043": "-",  # ⁃ hyphen bullet
        "\u2026": "...",  # … ellipsis
        "\u00b7": "-",  # · middle dot, sering jadi pemisah header OCR
        "\u2022": "-",  # • bullet
        # Karakter yang tidak terlihat sama sekali tapi tetap kotor: soft
        # hyphen PDF dan zero-width. Dihapus, bukan dipetakan — tidak punya
        # bentuk ASCII yang bermakna. Soft hyphen lolos dari NFKC dan dari
        # pembersih noise (bukan baris), lalu menyusup ke tengah kata dan
        # merusak pencarian.
        ord("\u00ad"): None,  # soft hyphen
        ord("\u200b"): None,  # zero-width space
        ord("\u200c"): None,  # zero-width non-joiner
        ord("\u200d"): None,  # zero-width joiner
        ord("\u2060"): None,  # word joiner
        ord("\ufeff"): None,  # BOM / zero-width no-break space
    }
)


def normalize_symbols(text: str) -> str:
    """Samakan tanda baca varian ke bentuk ASCII standar.

    Hanya menyentuh tanda baca, tidak pernah isi kata. Tanpa langkah ini,
    kutipan keriting hasil OCR/VLM lolos ke chunk dan membuat pencarian
    kata berfrasa ("'...'")
    gagal cocok dengan indeks yang memakai ASCII.
    """
    if not text:
        return text
    return text.translate(_SYMBOL_MAP)


#: Kata terpotong di akhir baris: "Undang-Undan-\ng". Pada teks Indonesia,
#: hyphen yang jatuh tepat di akhir baris hasil OCR hampir selalu sisa
#: pemenggalan kata oleh lebar kolom, bukan tanda hubung sah (kata berimbuhan
#: ber-hyphen seperti "anti-korupsi" nyaris tidak pernah berakhir tepat di
#: tepi baris). Penyambungan dilakukan hanya pada pola huruf-hyphen-akhir
#: baris-huruf, sehingga hyphen di tengah baris ("ke-) tidak disentuh.
_BROKEN_WORD_RE = re.compile(r"(?<=[a-zà-ÿ])-\n(?=[a-zà-ÿ])", re.IGNORECASE)


def join_broken_words(text: str) -> str:
    """Sambungkan kata yang terpotong hyphen di akhir baris.

    OCR memotong kata mengikuti lebar kolom: "pemerin-tahan", "Undang-
    Undan". Pada ejaan Indonesia, gabungan tanpa hyfen adalah bentuk
    utuhnya (awalan "ke-", "anti-", "pasca-" juga melekat tanpa hyfen saat
    jadi satu kata), jadi penyambungan cukup menghapus "hyfen + newline".
    Hyfen di tengah baris disengaja tidak disentuh: itu tanda hubung sah
    ("sosiologis-politis") yang memang harus tetap ada.
    """
    if not text:
        return text
    return _BROKEN_WORD_RE.sub("", text)


def clean_page_text(text: str) -> str:
    """Bersihkan teks satu halaman hasil ekstraksi PDF.

    Urutannya: normalisasi unicode, samakan tanda baca varian, buang baris
    noise, sambungkan kata terpotong di akhir baris, pecahkan kata yang
    meleleh (word-fusion), lalu rapikan whitespace. Normalisasi NFKC wajib
    lebih dulu: PP-OCR terlatih pada korpus CJK sering mengeluarkan tanda
    kurung/dash fullwidth ("（1）" untuk "(1)"), dan itu merusak regex
    ayat/butir maupun pencarian "ayat (3)".
    """
    cleaned = unicodedata.normalize("NFKC", text)
    cleaned = normalize_symbols(cleaned)
    cleaned = strip_noise_lines(cleaned)
    cleaned = join_broken_words(cleaned)
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
        "yang", "di", "ke", "dari", "pada", "kepada", "oleh", "untuk", "dengan", "tanpa",
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
        # Kata struktur pemerintahan & administrasi frekuensi tinggi pada
        # Peraturan/Perpres/Lembaran Negara di luar domain pengaduan. Dipilih
        # dari kata yang benar-benar sering muncul menyatu ("pemerintahpusat",
        # "kabupatendaerah") supaya pemecahannya berani tapi tetap sah.
        "pemerintah", "pemerintahan", "kementerian", "kantor", "dinas",
        "badan", "komisi", "komisioner", "panitia", "tim", "pelaksana",
        "pengawas", "pembina", "kepala", "sekretaris", "direktur", "unit",
        "kerja", "fungsi", "fungsional", "administrasi", "arsip",
        "provinsi", "kabupaten", "kota", "kecamatan", "kelurahan", "desa",
        "daerah", "wilayah", "pusat", "warga", "penduduk",
        "perizinan", "izin", "lisensi", "pendaftaran", "registrasi",
        "permohonan", "persyaratan", "syarat", "verifikasi", "validasi",
        "pengesahan", "sertifikat", "dokumen", "berkas", "data", "informasi",
        "sistem", "terpadu", "prosedur", "mekanisme", "tahapan", "alur",
        "laporan", "pertanggungjawaban", "anggaran", "pendapatan", "belanja",
        "pembiayaan", "kontrak", "perjanjian", "penyedia", "spesifikasi",
        "kompeten", "kompetensi", "ahli", "pakar", "baku", "utuh",
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
#: fragmen 1-2 huruf tak dikenal memenangkan pemecahan yang seharusnya
#: mempertahankan kata sah panjang ("pengelolaan" terbelah jadi "pengelola an").
_FUSION_MIN_PIECE_LEN = 3


_BEST = tuple[int, int, list[int]] | None


def _segment_fusion(token: str) -> list[str] | None:
    """Pecahkan satu token jadi kata-kata kamus bila solusinya meyakinkan.

    Algoritma: pemrograman dinamis yang mencari pemecahan dengan jumlah kata
    tak dikenal paling sedikit; di antara solusi ber-unknown sama, yang
    dipilih adalah yang PECAHANNYA PALING SEDIKIT. Tiebreak ini kebalikan
    dari versi lama ("makin banyak kata makin halus"), dan dibalik karena
    kasus nyata yang merusak: "DirektoralJenderal..." terbelah jadi
    "Di" + sisanya — "di" ada di kamus, jadi kedua solusi sama-sama punya
    satu kata tak dikenal, dan lebih-banyak-kata memenangkan pemenggalan
    yang salah di kata sapaan kapital. Memilih pecahan tersedikit menempatkan
    token yang tidak bisa dijelaskan kamus sebagai SATU kata utuh, yang jauh
    lebih aman. Mengembalikan ``None`` kalau solusi terbaiknya masih memuat
    lebih dari ``_FUSION_MAX_UNKNOWN`` kata tak dikenal — token ini
    kemungkinan bukan word-fusion, dan membiarkan apa adanya lebih aman
    daripada menebak.

    Batas tambahan: pecahan yang BUKAN anggota kamus harus panjangnya >= 3
    huruf. Tanpa ini, pecahan pendek tak dikenal (mis. "an") bisa lolos dan
    mengalahkan solusi yang mempertahankan kata sah panjang ("pengelolaan"
    terbelah jadi "pengelola an").
    """
    length = len(token)
    # cost[i] = (jumlah kata tak dikenal, jumlah total pecahan) — tie dipecah
    # oleh jumlah pecahan: makin SEDIKIT makin baik (lihat docstring).
    best: list[_BEST] = [None] * (length + 1)
    best[length] = (0, 0, [])

    for start in range(length - 1, -1, -1):
        for end in range(start + 1, length + 1):
            rest = best[end]
            if rest is None:
                continue
            piece = token[start:end]
            # Deretan angka ATOMIK: boleh jadi pecahan hanya kalau ia run digit
            # yang UTUH (tidak berbatasan dengan digit lain di kedua sisinya),
            # dan pecahan campuran huruf+digit dilarang sama sekali. Angka dalam
            # fusion ("2008", "38") adalah tahun/nomor dokumen yang utuh di teks
            # asli; membiarkannya dipecah menghasilkan "2 0 0 8" yang jauh lebih
            # merusak daripada tidak memecah sama sekali. Kata Indonesia tidak
            # mengandung digit di tengahnya, jadi batasan ini tidak pernah
            # memotong kata sah.
            if piece.isdigit():
                if (start > 0 and token[start - 1].isdigit()) or (
                    end < length and token[end].isdigit()
                ):
                    continue
                unknown = 0
            elif any(char.isdigit() for char in piece):
                continue
            # Pecahan di luar kamus wajib cukup panjang — fragmen 1-2 huruf
            # ("an", "ke", "la") nyaris pasti bukan kata, hanya sisa potongan
            # salah dari pecahan sah yang seharusnya utuh. Kata tugas pendek
            # sah tetap boleh karena ada di kamus ("di", "ke", "dan").
            elif piece.lower() in _LEXICON:
                # Pencarian kamus tak peduli kapitalisasi: OCR suka
                # mengkapitalkan awal baris, dan "Tahun" di awal baris tetap
                # kata yang sama dengan "tahun" di tengah kalimat.
                unknown = 0
            elif len(piece) < _FUSION_MIN_PIECE_LEN:
                continue
            else:
                unknown = 1
            candidate_unknown = rest[0] + unknown
            if candidate_unknown > _FUSION_MAX_UNKNOWN:
                continue
            candidate_pieces = rest[1] + 1
            candidate = (candidate_unknown, candidate_pieces, [start, *rest[2]])
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


#: Token yang layak dicoba dipecah: diawali huruf, cukup panjang, dan boleh
#: mengandung digit di tengah — Lembaran Negara sering menggabungkan kata dan
#: angka jadi satu token ("Tahun2008Nomor", "Pasal12Ayat1"). Token murni
#: angka ("2008") tetap tidak disentuh: itu isi sah yang sudah benar.
_FUSION_TOKEN_RE = re.compile(rf"[A-Za-z][A-Za-z0-9]{{{_FUSION_MIN_LEN - 1},}}")


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


# --------------------------------------------------------------------------
# Koreksi salah-OCR berbasis leksikon korpus (pass level DOKUMEN).
#
# Prinsipnya "self-consistency": kata yang muncul berulang kali dalam dokumen
# yang sama hampir pasti dibaca benar minimal sekali, jadi frekuensinya bisa
# dipakai sebagai kamus kebenaran dokumen itu sendiri. Token yang TIDAK ada
# di kamus tapi bentuk kanoniknya (dengan huruf yang lazim tertukar saat
# pemindaian) bertabrakan dengan kata kamus, dikoreksi ke kata itu — TANPA
# menyentuh token yang sudah ada di kamus.
#
# Ini bukan koreksi buta: satu token langka yang kebetulan bertabrakan bisa
# salah dikoreksi, tapi peluangnya jauh lebih kecil daripada peluang salah
# baca OCR yang dikoreksi benar, dan korpus legal memang repetitif.
# --------------------------------------------------------------------------

#: Pasangan huruf yang lazim tertukar saat pemindaian cetak (rn~m, cl~d,
#: ii~u, vv~w) dan karakter yang tertukar (c~e, l~i, 1~i, 0~o). Bentuk
#: kanonik menormalkan SEMUA variasi ini supaya salah baca dan kata benar
#: bertemu di bentuk yang sama.
_CANON_SWAPS = (("rn", "m"), ("cl", "d"), ("ii", "u"), ("vv", "w"))
_CANON_TABLE = str.maketrans({"c": "e", "l": "i", "1": "i", "|": "i", "0": "o"})

#: Frekuensi minimum sebuah kata di dokumen untuk dianggap kebenaran.
#: 3 dipilih dari pipeline eksternal yang teruji pada Perpres 76/2013; kata
#: yang muncul 1-2 kali tidak cukup dipercaya sebagai acuan.
_LEXICON_MIN_FREQ = 3

#: Token kandidat koreksi: inti alfabet minimal ini (di bawahnya, kata sah
#: pendek berisiko salah koreksi lebih besar daripada manfaatnya).
_TYPO_CORE_MIN_LEN = 4

_CORPUS_WORD_RE = re.compile(r"[A-Za-z]{4,}")
_TOKEN_SPLIT_RE = re.compile(r"^(\W*)(.*?)(\W*)$", re.S)


def canon_form(word: str) -> str:
    """Bentuk kanonik satu kata: huruf tertukar dan karakter penggantinya disamakan.

    Huruf besar diabaikan; dipakai untuk mencocokkan salah baca dengan kata
    kamus tanpa peduli kapitalisasi maupun karakter yang tertukar.
    """
    lowered = word.lower()
    for old, new in _CANON_SWAPS:
        lowered = lowered.replace(old, new)
    return lowered.translate(_CANON_TABLE)


def build_corpus_lexicon(lines: list[str]) -> dict[str, int]:
    """Kamus kebenaran dari korpus yang sama: kata muncul >= 3 kali.

    Dipanggil sekali per dokumen (pass level dokumen), bukan per halaman:
    kata langka di satu halaman bisa berulang di halaman lain.
    """
    counter: dict[str, int] = {}
    for line in lines:
        for word in _CORPUS_WORD_RE.findall(line):
            lowered = word.lower()
            counter[lowered] = counter.get(lowered, 0) + 1
    return {word: count for word, count in counter.items() if count >= _LEXICON_MIN_FREQ}


def _correct_token(
    token: str,
    lexicon: dict[str, int],
    canon_map: dict[str, str],
    by_length: dict[int, list[str]],
) -> str:
    """Koreksi satu token bila yakin; selain itu kembalikan apa adanya.

    Yakin berarti: intinya >= 4 huruf tanpa digit, tidak ada di kamus, DAN
    bentuk kanoniknya menunjuk ke kata kamus yang ada. Simbol liar di tengah
    kata ("pa~a") dicoba sebagai wildcard terhadap kamus dulu — itu pola noda
    tinta yang khas, bukan ejaan.
    """
    match = _TOKEN_SPLIT_RE.match(token)
    if match is None:
        return token
    prefix, core, suffix = match.groups()
    if len(core) < _TYPO_CORE_MIN_LEN or not core.isalpha():
        return token
    lowered = core.lower()
    if lowered in lexicon:
        return token

    if re.search(r"[A-Za-z][~.^`'][A-Za-z]", core):
        pattern = re.compile("^" + re.sub(r"[~.^`']", ".", lowered) + "$")
        hits = [w for w in by_length.get(len(core), []) if pattern.match(w)]
        if hits:
            return prefix + _preserve_case(core, max(hits, key=lexicon.get)) + suffix
        stripped = re.sub(r"[~.^`']", "", core)
        if stripped.lower() in lexicon:
            return prefix + _preserve_case(core, stripped.lower()) + suffix
        core = stripped
        lowered = core.lower()
        if len(core) < _TYPO_CORE_MIN_LEN or lowered in lexicon:
            return token

    canonical = canon_form(core)
    target = canon_map.get(canonical)
    if target is not None and target != lowered:
        return prefix + _preserve_case(core, target) + suffix
    return token


def _preserve_case(original: str, corrected: str) -> str:
    """Pertahankan kapitalisasi token asli pada kata hasil koreksi."""
    if original.isupper():
        return corrected.upper()
    if original[:1].isupper():
        return corrected[:1].upper() + corrected[1:]
    return corrected


def correct_document_typos(pages: list[str]) -> list[str]:
    """Koreksi salah-OCR di semua halaman memakai leksikon dokumen itu sendiri.

    Pass level dokumen dijalankan SETELAH pembersihan per halaman selesai —
    leksikonnya harus lihat seluruh dokumen, bukan satu halaman. Baris
    heading pendek ("Pasal 5") tidak memenuhi syarat panjang kandidat
    koreksi, jadi struktur dokumen aman tanpa perlindungan khusus.
    """
    lines = [(page, line) for page, text in enumerate(pages) for line in text.split("\n")]
    lexicon = build_corpus_lexicon([line for _page, line in lines])
    if not lexicon:
        return pages
    by_length: dict[int, list[str]] = {}
    canon_map: dict[str, str] = {}
    for word in sorted(lexicon, key=lexicon.get, reverse=True):
        by_length.setdefault(len(word), []).append(word)
        canon_map.setdefault(canon_form(word), word)
    corrected = [
        " ".join(_correct_token(token, lexicon, canon_map, by_length) for token in line.split())
        for _page, line in lines
    ]
    # Susun ulang per halaman; baris kosong ikut sehingga pemisah paragraf
    # ("\n\n") tetap utuh.
    rebuilt: list[list[str]] = [[] for _ in pages]
    for (page, _line), text in zip(lines, corrected, strict=True):
        rebuilt[page].append(text)
    return ["\n".join(lines_of_page) for lines_of_page in rebuilt]


# --------------------------------------------------------------------------
# Perbaikan penanda butir/ayat yang rusak hasil OCR (pass level dokumen).
#
# Dua kegagalan khas OCR pada Lembaran Negara yang tidak bisa diperbaiki
# per-halaman: (1) penanda butir dua huruf ("Cc." untuk "c." — huruf
# penanda terbaca dua kali), yang bisa dipulihkan dari URUTAN ABJAD butir
# sebelumnya; (2) angka penanda daftar definisi yang hilang sama sekali,
# yang bisa dipulihkan dari pola "baris sebelumnya berakhir titik + baris
# ini diawali kapital". Keduanya lintas halaman: butir dan daftar definisi
# sering menyeberang halaman.
# --------------------------------------------------------------------------

_RE_ITEM = re.compile(r"^([a-z]|\d{1,2})\.\s")
_RE_AYAT = re.compile(r"^\((\d+)\)\s")
_RE_STRUCTURE_START = re.compile(r"^(Pasal\s*\d+|BAB\s*[IVXLC]+|Bagian\s+[A-Z])")
_RE_MISREAD_NUMBER = re.compile(r"^(Ii|Il|li|ll|I1|l1)\s+[A-Z]")
_RE_DEFINITION_LIST = re.compile(r"yang dimaksud dengan:$")
_RE_LIST_NUMBER = re.compile(r"^(\d{1,2})\.\s")


def repair_list_markers(tagged: list[tuple[int, str]]) -> list[tuple[int, str]]:
    """Pulihkan penanda butir dua huruf dan tanda baca akhir butir.

    (1) "Cc." setelah "b." menjadi "c." — diterima hanya kalau huruf urutan
    abjad berikutnya memang ada di dalam penanda yang rusak; (2) titik dua/
    koma di akhir butir yang terbaca salah dipulihkan dari penanda butir/
    ayat BERIKUTNYA (butir selalu berakhir ";" kecuali yang terakhir ".").
    """
    out = list(tagged)
    last_letter: str | None = None
    for index, (_page, text) in enumerate(out):
        if _RE_STRUCTURE_START.match(text) or _RE_AYAT.match(text):
            last_letter = None
        single = re.match(r"^([A-Za-z])\.\s", text)
        if single:
            last_letter = single.group(1).lower()
            continue
        doubled = re.match(r"^([A-Za-z]{2})\.\s", text)
        if doubled and last_letter:
            expected = chr(ord(last_letter) + 1)
            if expected in doubled.group(1).lower():
                out[index] = (
                    _page,
                    expected + ". " + text[len(doubled.group(0)) :],
                )
                last_letter = expected

    for index in range(len(out) - 1):
        _page, text = out[index]
        nxt = out[index + 1][1]
        item = _RE_ITEM.match(nxt)
        ayat = _RE_AYAT.match(nxt)
        if item and item.group(1) not in ("a", "1"):
            # Butir berikutnya bukan pembuka daftar → baris ini akhir butir:
            # pemisah antar butir adalah titik koma, bukan titik dua/koma.
            out[index] = (_page, re.sub(r"[:,]$", ";", text))
        elif re.match(r"^Mengingat\b", nxt):
            out[index] = (_page, re.sub(r"[:,]$", ";", text))
        elif ayat and int(ayat.group(1)) > 1:
            # Ayat berikutnya bukan ayat (1) → baris ini akhir ayat: akhiri
            # dengan titik, bukan titik dua/koma hasil salah baca.
            out[index] = (_page, re.sub(r"[:,]$", ".", text))
    return out


def restore_definition_markers(
    tagged: list[tuple[int, str]]
) -> list[tuple[int, str]]:
    """Pulihkan nomor penanda daftar definisi yang hilang atau salah baca.

    OCR sering menghilangkan angka penanda di kolom kiri ("2." terbaca ".",
    "11." terbaca "Ii"). Di dalam daftar definisi ("... yang dimaksud
    dengan:"), awal butir baru dikenali dari baris sebelumnya yang berakhir
    titik dan baris ini diawali huruf kapital; nomornya dipulihkan berurutan
    dan disinkronkan dengan penanda yang berhasil terbaca.
    """
    out: list[tuple[int, str]] = []
    in_list = False
    counter = 0
    previous = ""
    for page, text in tagged:
        if _RE_DEFINITION_LIST.search(text):
            in_list, counter = True, 0
            out.append((page, text))
            previous = text
            continue
        if in_list and (
            _RE_STRUCTURE_START.match(text)
            or re.match(r"^(Menimbang|Mengingat|Menetapkan)\b", text)
        ):
            in_list = False
        if in_list:
            numbered = _RE_LIST_NUMBER.match(text)
            if numbered:
                counter = int(numbered.group(1))
            elif previous.endswith(".") and (
                re.match(r"^[.,]?\s*[A-Z]", text) or _RE_MISREAD_NUMBER.match(text)
            ):
                text = re.sub(r"^([.,]\s*|(Ii|Il|li|ll|I1|l1)\s+)", "", text)
                counter += 1
                text = f"{counter}. {text}"
        out.append((page, text))
        previous = text
    return out


def repair_document_pages(
    pages: list[str], *, typo_correction: bool = True, repair_markers: bool = True
) -> list[str]:
    """Pass level dokumen: koreksi typo leksikon, lalu perbaiki penanda.

    Urutan penting: koreksi typo dahulu (agar "Cc." yang berasal dari salah
    baca bisa menjadi penanda yang dikenali perbaikan penanda), lalu
    perbaikan penanda butir/ayat yang bekerja lintas halaman. Dipanggil
    sekali per dokumen di akhir OCR, bukan per halaman. Baris kosong ikut
    dibawa utuh sehingga pemisah paragraf tidak bergeser.
    """
    if typo_correction:
        pages = correct_document_typos(pages)
    if not repair_markers:
        return pages
    tagged = [
        (page, line)
        for page, text in enumerate(pages)
        for line in text.split("\n")
    ]
    repaired = restore_definition_markers(repair_list_markers(tagged))
    rebuilt: list[list[str]] = [[] for _ in pages]
    for (page, _line), (_repaired_page, text) in zip(tagged, repaired, strict=True):
        rebuilt[page].append(text)
    return ["\n".join(lines_of_page) for lines_of_page in rebuilt]
