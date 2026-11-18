"""Tahap 2 - bersihkan hasil OCR.

* buang kop / nomor halaman / penanda lanjutan ('dalam ...') / noise (tanpa menyentuh judul Pasal/BAB/Bagian)
* koreksi salah-OCR dengan leksikon internal korpus + kesamaan 'kanonik' huruf yang sering tertukar
  (c~e, l~i~1, rn~m, cl~d) -> tidak mengubah kata valid yang jarang muncul
* perbaiki penanda butir/ayat dan tanda baca akhir butir
* sambung baris & kata terpotong, lintas halaman, sambil mencatat halaman asal
"""
from __future__ import annotations

import re
from collections import Counter

from ocr_pipeline import PageResult

WORD = re.compile(r"[A-Za-z]{4,}")
RE_HEADING = re.compile(r"^(Pasal\s*\d+|BAB\s*[IVXLC]+|Bagian\s+[A-Z][a-z]+)\s*$")

# ----------------------------------------------------------------------------- furniture
RE_PAGENUM = re.compile(r"^[\-–—~.\s]*[A-Za-z]?\d{1,3}[\-–—~.\s]*$")


def strip_page_furniture(page: PageResult) -> list[str]:
    """Baris isi halaman tanpa kop, nomor halaman, penanda lanjutan, dan noise.
    Penanda lanjutan dikenali dari POSISI: baris pendek rata-kanan di zona bawah ('(2) Penyediaan ...')."""
    H, W = page.height, page.width
    out: list[str] = []
    for ln in page.lines:
        t = re.sub(r"^[^\w(]+", "", ln.text.strip())      # buang garis/lipatan di awal baris ('— Bagian Kesembilan')
        t = re.sub(r"^BAB\s*([IVXLC]+)\.*$", r"BAB \1", t)  # 'BABI' -> 'BAB I'
        x0, y0, _, y1 = ln.bbox
        if y1 > 0.80 * H and x0 > 0.60 * W and len(t.split()) <= 4:
            continue                                  # catchword rata-kanan di bawah halaman (cek SEBELUM heading: 'BAB II ...')
        if RE_HEADING.match(t):                       # judul struktur tidak boleh hilang walau conf rendah
            out.append(t)
            continue
        if y0 < 0.22 * H:
            core = t.replace("|", "").strip()
            if re.fullmatch(r"(PRESIDEN|REPUBLIK(\s+INDONESIA)?)", core, re.I) or RE_PAGENUM.match(core):
                continue
        if ln.conf < 70 and (len(t) < 12 or sum(c.isalnum() for c in t) < 0.6 * len(t)):
            continue
        if not re.search(r"[A-Za-z0-9]{2,}", t):
            continue
        out.append(t)
    return out


# ----------------------------------------------------------------------------- leksikon & koreksi
def build_lexicon(all_lines: list[str], min_freq: int = 3) -> Counter:
    """Kata yang muncul >= min_freq kali di dokumen yang sama dianggap benar (self-consistency)."""
    c = Counter(w.lower() for t in all_lines for w in WORD.findall(t))
    return Counter({w: n for w, n in c.items() if n >= min_freq})


def canon(w: str) -> str:
    """Bentuk kanonik: samakan huruf yang lazim tertukar pada scan cetak."""
    w = w.lower()
    for a, b in (("rn", "m"), ("cl", "d"), ("ii", "u"), ("vv", "w")):
        w = w.replace(a, b)
    return w.translate(str.maketrans({"c": "e", "l": "i", "1": "i", "|": "i", "0": "o"}))


def _case(orig: str, new: str) -> str:
    if orig.isupper():
        return new.upper()
    return new[:1].upper() + new[1:] if orig[:1].isupper() else new


def correct_token(tok: str, lex: Counter, canon_map: dict[str, str], by_len: dict[int, list[str]]) -> str:
    pre, core, post = re.match(r"^(\W*)(.*?)(\W*)$", tok).groups()
    if len(core) < 4 or core.lower() in lex:
        return tok
    # simbol liar di tengah kata: 'pa~a' -> wildcard terhadap leksikon; 'publi.k' -> buang simbol
    if re.search(r"[A-Za-z][~\.\|\^`'][A-Za-z]", core):
        pat = re.compile("^" + re.sub(r"[~\.\|\^`']", ".", core.lower()) + "$")
        hits = [w for w in by_len.get(len(core), []) if pat.match(w)]
        if hits:
            return pre + _case(core, max(hits, key=lex.get)) + post
        stripped = re.sub(r"[~\.\|\^`']", "", core)
        if stripped.lower() in lex:
            return pre + _case(core, stripped.lower()) + post
        core = stripped
    c = canon(core)
    if c in canon_map and canon_map[c] != core.lower():
        return pre + _case(core, canon_map[c]) + post
    return tok


def correct_lines(lines: list[str], lex: Counter) -> list[str]:
    by_len: dict[int, list[str]] = {}
    canon_map: dict[str, str] = {}
    for w in sorted(lex, key=lex.get):                 # frekuensi tertinggi menimpa terakhir
        by_len.setdefault(len(w), []).append(w)
        canon_map[canon(w)] = w
    return [" ".join(correct_token(t, lex, canon_map, by_len) for t in ln.split()) for ln in lines]


# ----------------------------------------------------------------------------- tanda baca & penanda
def normalize_punct(lines: list[str]) -> list[str]:
    fixed = []
    for t in lines:
        t = t.replace("\u201c", "").replace("\u201d", "").replace('"', "")          # petik liar akibat noda
        t = re.sub(r"\s*\|\s*", " ", t).strip(" |_~\\")                              # garis lipatan terbaca '|'
        t = re.sub(r"\s[\-–—~]+\s", " ", t)                                          # tanda hubung/garis sendirian
        # penanda ayat: '(l)', '(4/', '(5)Ketentuan' -> '(1) ', '(4) ', '(5) Ketentuan'
        t = re.sub(r"^\(\s*([0-9lIO]{1,2})\s*[\)\/\]\}]\s*",
                   lambda m: "(" + m.group(1).translate(str.maketrans("lIO", "110")) + ") ", t)
        t = re.sub(r"^((?:Menimbang|Mengingat)\s*:\s*)?([a-z])\2\.\s", lambda m: (m.group(1) or "") + m.group(2) + ". ", t)  # 'aa.' -> 'a.'
        t = re.sub(r"(?<=[A-Za-z]{3})\.\s+(?=[a-z])", " ", t)                        # titik nyasar di tengah kalimat
        t = re.sub(r"\s+([,;:.])", r"\1", t)
        t = re.sub(r"\s{2,}", " ", t).rstrip()
        t = re.sub(r"(\.{2,}|…)$", "", t).rstrip()
        fixed.append(t)
    return [t for t in fixed if t]


RE_ITEM = re.compile(r"^([a-z]|\d{1,2})\.\s")
RE_AYAT = re.compile(r"^\((\d+)\)\s")


def repair_endings(tagged: list[tuple[int, str]]) -> list[tuple[int, str]]:
    """Berjalan lintas halaman. (1) penanda butir 2 huruf ('Cc.', 'ec.') dipulihkan memakai urutan abjad
    yang diharapkan; (2) tanda baca akhir butir ';' yang terbaca ':' / ',' dipulihkan dari penanda berikutnya."""
    out = list(tagged)
    last_letter = None
    for i, (p, t) in enumerate(out):
        if re.match(r"^(Pasal\s+\d+|\(\d+\)\s)", t):
            last_letter = None
        m = re.match(r"^([A-Za-z])\.\s", t)
        if m:
            last_letter = m.group(1).lower()
            continue
        m2 = re.match(r"^([A-Za-z]{2})\.\s", t)
        if m2 and last_letter:
            exp = chr(ord(last_letter) + 1)
            if exp in m2.group(1).lower():
                out[i] = (p, exp + ". " + t[len(m2.group(0)):])
                last_letter = exp
    for i in range(len(out) - 1):
        p, t = out[i]
        nxt = out[i + 1][1]
        item, ay = RE_ITEM.match(nxt), RE_AYAT.match(nxt)
        if item and item.group(1) not in ("a", "1"):       # bukan butir pertama -> t adalah butir
            t = re.sub(r"[:,]$", ";", t)
            t = re.sub(r",( dan)$", r";\1", t)
            out[i] = (p, t)
        elif re.match(r"^Mengingat\b", nxt):
            out[i] = (p, re.sub(r"[:,]$", ";", t))
        elif ay and int(ay.group(1)) > 1:
            out[i] = (p, re.sub(r"[:,]$", ".", t))
    return out


def restore_definition_markers(tagged: list[tuple[int, str]]) -> list[tuple[int, str]]:
    """Tesseract sering menghilangkan angka penanda di kolom kiri ('2.' -> '.', '7.' -> hilang, '11.' -> 'Ii').
    Pada daftar definisi ('... yang dimaksud dengan:'), awal butir baru dikenali dari: baris sebelumnya berakhir
    '.' dan baris ini diawali huruf kapital; nomor dipulihkan berurutan dan disinkronkan dengan penanda yang terbaca."""
    out, in_list, n = [], False, 0
    prev = ""
    for page, t in tagged:
        if re.search(r"yang dimaksud dengan:$", t):
            in_list, n, prev = True, 0, t
            out.append((page, t))
            continue
        if in_list and (RE_HEADING.match(t) or re.match(r"^(BAB|Bagian|Pasal)\b", t)):
            in_list = False
        if in_list:
            m = re.match(r"^(\d{1,2})\.\s", t)
            if m:
                n = int(m.group(1))
            elif prev.endswith(".") and (re.match(r"^[.,]?\s*[A-Z]", t) or re.match(r"^(Ii|Il|li|ll|I1|l1)\s+[A-Z]", t)):
                t = re.sub(r"^([.,]\s*|(Ii|Il|li|ll|I1|l1)\s+)", "", t)
                n += 1
                t = f"{n}. {t}"
        out.append((page, t))
        prev = t
    return out


RE_START = re.compile(
    r"^(BAB\s*[IVXLC]+\b|Bagian\s+[A-Z]|Pasal\s+\d+\s*$|\(\d+\)\s|[a-z]\.\s|\d{1,2}\.\s|"
    r"Menimbang\b|Mengingat\b|Menetapkan\b|MEMUTUSKAN|Agar setiap orang|Ditetapkan di|Diundangkan di|"
    r"LEMBARAN NEGARA|Salinan sesuai|ttd\.|SEKRETARIAT|Deputi|MENTERI|PRESIDEN REPUBLIK INDONESIA,|DENGAN RAHMAT)")


def join_wrapped(tagged: list[tuple[int, str]], lex: Counter) -> list[dict]:
    """Gabungkan baris lanjutan menjadi butir/ayat utuh (lintas halaman) + catat halaman awal-akhir.
    'penga- duan' disambung bila hasil gabungan ada di leksikon; 'sekurang-kurangnya' dipertahankan."""
    paras: list[dict] = []
    for page, t in tagged:
        prev = paras[-1] if paras else None
        if prev and not RE_START.match(t) and not RE_HEADING.match(prev["text"]):
            m = re.search(r"(\w+)-$", prev["text"])
            if m:
                first, _, rest = t.partition(" ")
                glued = (m.group(1) + first).lower()
                prev["text"] = (prev["text"][:-1] + first) if glued in lex else (prev["text"] + first)
                prev["text"] += (" " + rest) if rest else ""
            else:
                prev["text"] += " " + t
            prev["page_end"] = page
        else:
            paras.append({"text": t, "page_start": page, "page_end": page})
    return paras


# ----------------------------------------------------------------------------- orkestrasi
def clean_document(pages: list[PageResult]) -> tuple[list[dict], Counter]:
    """OCR mentah -> paragraf bersih [{text, page_start, page_end}] + leksikon yang dipakai."""
    raw = [(p.page, strip_page_furniture(p)) for p in pages]
    lex = build_lexicon([l for _, ls in raw for l in ls])
    tagged: list[tuple[int, str]] = []
    for page_no, lines in raw:
        tagged += [(page_no, l) for l in normalize_punct(correct_lines(lines, lex))]
    return join_wrapped(restore_definition_markers(repair_endings(tagged)), lex), lex
