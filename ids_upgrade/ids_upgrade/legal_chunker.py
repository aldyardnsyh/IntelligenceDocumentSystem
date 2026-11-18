"""Tahap 3 - chunking sadar-struktur untuk peraturan perundang-undangan Indonesia.

Satuan chunk = Pasal (atau ayat/butir bila pasal panjang / berupa daftar definisi), bukan jendela karakter.
Setiap chunk membawa metadata hierarki (BAB > Bagian > Pasal > ayat), halaman, sitasi siap-pakai,
dan 'contextual_text' (teks yang di-embed) berisi header konteks agar retrieval tidak kehilangan 'siapa/apa'.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict

RE_BAB = re.compile(r"^BAB\s+([IVXLC]+)$")
RE_BAGIAN = re.compile(r"^Bagian\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)$")
RE_PASAL = re.compile(r"^Pasal\s+(\d+)$")
RE_AYAT = re.compile(r"^\((\d+)\)\s+(.*)$", re.S)
RE_BUTIR_NUM = re.compile(r"^(\d{1,2})\.\s+(.*)$", re.S)
RE_BUTIR_HURUF = re.compile(r"^([a-z])\.\s+(.*)$", re.S)

LABELS = {"Menimbang": "menimbang", "Mengingat": "mengingat"}
MAX_CHARS_PER_CHUNK = 1100          # di atas ini, pasal dipecah per ayat/butir (small-to-big)


@dataclass
class Chunk:
    id: str
    chunk_type: str                   # pasal | ayat | butir | pembukaan | penutup | visual
    text: str
    contextual_text: str
    citation: str
    doc_title: str
    page_start: int
    page_end: int
    bab: str | None = None
    bab_title: str | None = None
    bagian: str | None = None
    bagian_title: str | None = None
    pasal: int | None = None
    ayat: int | None = None
    butir: str | None = None
    parent_id: str | None = None
    parent_text: str | None = None
    extra: dict = field(default_factory=dict)

    def to_dict(self):
        return asdict(self)


def _pages(a, b):
    return f"hlm. {a}" if a == b else f"hlm. {a}-{b}"


def build_chunks(paras: list[dict], doc_title: str, doc_short: str, visuals: list | None = None) -> tuple[list[Chunk], list[str]]:
    """paras: keluaran text_cleaning.clean_document. Kembalikan (chunks, peringatan_validasi)."""
    warnings: list[str] = []
    state = {"bab": None, "bab_title": None, "bagian": None, "bagian_title": None}
    pasals: list[dict] = []
    pre: list[dict] = []
    post: list[dict] = []
    cur: dict | None = None
    expect_title = None
    seen_pasal = False

    for p in paras:
        t, ps, pe = p["text"], p["page_start"], p["page_end"]
        if expect_title:
            state[expect_title + "_title"] = t
            expect_title = None
            continue
        if m := RE_BAB.match(t):
            state.update(bab=m.group(1), bab_title=None, bagian=None, bagian_title=None)
            expect_title, cur = "bab", None
            seen_pasal = True
            continue
        if m := RE_BAGIAN.match(t):
            state.update(bagian=m.group(1), bagian_title=None)
            expect_title, cur = "bagian", None
            continue
        if m := RE_PASAL.match(t):
            no = int(m.group(1))
            if pasals and no != pasals[-1]["no"] + 1:
                warnings.append(f"Urutan Pasal tidak berurutan: {pasals[-1]['no']} -> {no} (hlm. {ps})")
            cur = {"no": no, "items": [], "page_start": ps, "page_end": pe, **state}
            pasals.append(cur)
            seen_pasal = True
            continue
        if re.match(r"^(Agar setiap orang|Ditetapkan di|Diundangkan di|LEMBARAN NEGARA|Salinan sesuai|ttd\.|SEKRETARIAT|Deputi|MENTERI|PRESIDEN REPUBLIK INDONESIA,$|DR\.|AMIR|Bistok)", t) and pasals:
            cur = None
            post.append(p)
            continue
        if cur is None:
            (post if (pasals and not RE_AYAT.match(t) and seen_pasal and len(pasals) >= 1 and pasals[-1]["no"] >= 21) else pre).append(p)
            continue
        cur["items"].append(p)
        cur["page_end"] = max(cur["page_end"], pe)

    chunks: list[Chunk] = []

    # ---- pembukaan (menimbang / mengingat / judul)
    if pre:
        txt = "\n".join(re.sub(r"^(Menimbang|Mengingat|Menetapkan):\s*", r"\1: ", x["text"]) for x in pre)
        chunks.append(Chunk(
            id="pembukaan", chunk_type="pembukaan", text=txt,
            contextual_text=f"{doc_title} | Pembukaan (Menimbang, Mengingat, Menetapkan)\n{txt}",
            citation=f"{doc_short}, Pembukaan, {_pages(pre[0]['page_start'], pre[-1]['page_end'])}",
            doc_title=doc_title, page_start=pre[0]["page_start"], page_end=pre[-1]["page_end"]))

    # ---- pasal
    for ps_ in pasals:
        header = [f"{doc_title}"]
        if ps_["bab"]:
            header.append(f"BAB {ps_['bab']} {ps_['bab_title'] or ''}".strip())
        if ps_["bagian"]:
            header.append(f"Bagian {ps_['bagian']} {ps_['bagian_title'] or ''}".strip())
        header.append(f"Pasal {ps_['no']}")
        header_s = " > ".join(header)

        body = "\n".join(i["text"] for i in ps_["items"])
        pid = f"pasal-{ps_['no']}"
        common = dict(doc_title=doc_title, bab=ps_["bab"], bab_title=ps_["bab_title"],
                      bagian=ps_["bagian"], bagian_title=ps_["bagian_title"], pasal=ps_["no"])
        cit = f"{doc_short}, Pasal {ps_['no']}"
        parent = Chunk(id=pid, chunk_type="pasal", text=body,
                       contextual_text=f"{header_s}\n{body}", citation=f"{cit}, {_pages(ps_['page_start'], ps_['page_end'])}",
                       page_start=ps_["page_start"], page_end=ps_["page_end"], **common)
        chunks.append(parent)

        if len(body) > MAX_CHARS_PER_CHUNK or _is_definition_list(ps_["items"]):
            parent.extra["has_children"] = True          # indeks cukup anak-anaknya; induk dipakai untuk ekspansi konteks
            for sub in _split_children(ps_["items"]):
                label = f"ayat ({sub['ayat']})" if sub["ayat"] else f"butir {sub['butir']}"
                ctext = f"{header_s} > {label}\n{sub['text']}"
                chunks.append(Chunk(
                    id=f"{pid}-{('a' + str(sub['ayat'])) if sub['ayat'] else ('b-' + str(sub['butir']))}",
                    chunk_type="ayat" if sub["ayat"] else "butir", text=sub["text"], contextual_text=ctext,
                    citation=f"{cit} {label}, {_pages(sub['page_start'], sub['page_end'])}",
                    page_start=sub["page_start"], page_end=sub["page_end"],
                    ayat=sub["ayat"], butir=sub["butir"], parent_id=pid, parent_text=body, **common))

    # ---- penutup
    if post:
        txt = "\n".join(x["text"] for x in post)
        chunks.append(Chunk(
            id="penutup", chunk_type="penutup", text=txt,
            contextual_text=f"{doc_title} | Penutup: penetapan, pengundangan, penandatangan, Lembaran Negara\n{txt}",
            citation=f"{doc_short}, Penutup, {_pages(post[0]['page_start'], post[-1]['page_end'])}",
            doc_title=doc_title, page_start=post[0]["page_start"], page_end=post[-1]["page_end"]))

    # ---- chunk visual (multimodal). Elemen berulang di setiap halaman (lambang kop, paraf) digabung per jenis
    #      agar tidak membanjiri indeks; elemen unik (tanda tangan/stempel) tetap per kemunculan.
    REPEATING = {"lambang", "paraf"}
    groups: dict[str, list] = {}
    for v in visuals or []:
        groups.setdefault(v.kind if v.kind in REPEATING else f"{v.kind}-p{v.page}-{v.bbox[0]}", []).append(v)
    for key, vs in groups.items():
        v = vs[0]
        pages = sorted({x.page for x in vs})
        desc = v.caption or f"Elemen visual jenis '{v.kind.replace('_', ' ')}' di posisi {v.position}."
        if v.nearby_text:
            desc += f" Teks di dekatnya: {v.nearby_text}."
        if len(pages) > 1:
            desc += f" Muncul berulang pada halaman {pages[0]}-{pages[-1]} ({len(pages)} halaman)."
        chunks.append(Chunk(
            id=f"visual-{key}", chunk_type="visual", text=desc,
            contextual_text=f"{doc_title} | Elemen visual: {desc}",
            citation=f"{doc_short}, elemen visual ({v.kind.replace('_', ' ')}), hlm. {', '.join(map(str, pages)) if len(pages) <= 3 else f'{pages[0]}-{pages[-1]}'}",
            doc_title=doc_title, page_start=pages[0], page_end=pages[-1],
            extra={"bbox": list(v.bbox), "crop_path": v.crop_path, "kind": v.kind, "position": v.position, "pages": pages}))

    warnings += _validate(pasals)
    return chunks, warnings


def _is_definition_list(items: list[dict]) -> bool:
    return sum(bool(RE_BUTIR_NUM.match(i["text"])) for i in items) >= 4


def _split_children(items: list[dict]) -> list[dict]:
    """Pecah isi pasal menjadi ayat (beserta butir a., b. di dalamnya) atau butir bernomor (definisi)."""
    subs: list[dict] = []
    for it in items:
        t = it["text"]
        if m := RE_AYAT.match(t):
            subs.append(dict(ayat=int(m.group(1)), butir=None, text=t, page_start=it["page_start"], page_end=it["page_end"]))
        elif (m := RE_BUTIR_NUM.match(t)) and (not subs or subs[-1]["butir"]):
            subs.append(dict(ayat=None, butir=m.group(1), text=t, page_start=it["page_start"], page_end=it["page_end"]))
        elif subs:                                       # butir huruf / lanjutan menempel ke ayat sebelumnya
            subs[-1]["text"] += "\n" + t
            subs[-1]["page_end"] = max(subs[-1]["page_end"], it["page_end"])
        else:                                            # pengantar pasal ('Pengelola dilarang:')
            subs.append(dict(ayat=None, butir="pengantar", text=t, page_start=it["page_start"], page_end=it["page_end"]))
    return subs


def _validate(pasals: list[dict]) -> list[str]:
    w = []
    nums = [p["no"] for p in pasals]
    if nums and nums != list(range(nums[0], nums[-1] + 1)):
        w.append(f"Pasal tidak lengkap: ditemukan {nums}")
    for p in pasals:
        if not p["items"]:
            w.append(f"Pasal {p['no']} kosong (kemungkinan salah-OCR pada isi)")
        ay = [int(m.group(1)) for i in p["items"] if (m := RE_AYAT.match(i["text"]))]
        if ay and ay != list(range(1, len(ay) + 1)):
            w.append(f"Pasal {p['no']}: nomor ayat tidak berurutan {ay}")
    return w
