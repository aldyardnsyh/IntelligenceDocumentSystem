"""Evaluasi terhadap data valid (gold_perpres_76_2013.json):
  A. kualitas teks  : CER/WER teks lapisan-bawaan-PDF vs OCR mentah vs pipeline baru
  B. struktur       : Pasal/ayat/butir yang berhasil dipulihkan + kemiripan teks per Pasal
  C. retrieval      : hit@k untuk 24 pertanyaan (BM25 baseline; pasang retriever Anda sendiri lewat --retriever)

    python evaluate.py --pdf Perpres_76_2013.pdf --out out
    python evaluate.py --pdf ... --retriever my_module:search     # def search(question:str, k:int) -> list[str]
"""
from __future__ import annotations

import argparse
import importlib
import json
import re
import statistics

import jiwer
import pymupdf
from rank_bm25 import BM25Okapi
from rapidfuzz import fuzz

# ----------------------------------------------------------------------------- gold
def norm(s: str) -> str:
    return re.sub(r"\s+", " ", s.lower()).strip()


def toks(s: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", s.lower()))


def gold_units(g: dict) -> dict:
    """{ 'pasal-12': 'teks gabungan', ('pasal-12', 'a2'): ..., 'penutup': ...}"""
    units, text_pasal, ayat_units = {}, {}, {}
    for p in g["batang_tubuh"]:
        n = p["nomor_pasal"]
        parts = []
        if p["pengantar"]:
            parts.append(p["pengantar"])
        if p["teks"]:
            parts.append(p["teks"])
        parts += [f'{b["kode"]}. {b["teks"]}' for b in p["butir"]]
        for a in p["ayat"]:
            seg = [f'({a["nomor"]}) ' + (a["pengantar"] or a["teks"] or "")]
            seg += [f'{b["kode"]}. {b["teks"]}' for b in a["butir"]]
            ayat_units[(n, a["nomor"])] = " ".join(seg)
            parts.append(" ".join(seg))
        text_pasal[n] = " ".join(parts)
    return {"pasal": text_pasal, "ayat": ayat_units}


def gold_full_text(g: dict) -> str:
    m, pb, t = g["metadata"], g["pembukaan"], []
    t += [m["judul_lengkap"], pb["frasa_pembuka"], pb["pejabat_penetap"], "Menimbang"]
    t += [f'{x["kode"]}. {x["teks"]}' for x in pb["menimbang"]] + ["Mengingat"]
    t += [f'{x["nomor"]}. {x["teks"]}' for x in pb["mengingat"]]
    t += ["MEMUTUSKAN", "Menetapkan", pb["memutuskan"]["menetapkan"]]
    last_bab = last_bag = None
    for p in g["batang_tubuh"]:
        if p["bab"] != last_bab:
            t += [f'BAB {p["bab"]}', p["judul_bab"]]
            last_bab, last_bag = p["bab"], None
        if p["bagian"] and p["bagian"] != last_bag:
            t += [f'Bagian {p["bagian"]}', p["judul_bagian"]]
            last_bag = p["bagian"]
        t.append(f'Pasal {p["nomor_pasal"]}')
        if p["pengantar"]:
            t.append(p["pengantar"])
        if p["teks"]:
            t.append(p["teks"])
        for b in p["butir"]:
            t.append(f'{b["kode"]}. {b["teks"]}')
        for a in p["ayat"]:
            t.append(f'({a["nomor"]}) ' + (a["pengantar"] or a["teks"] or ""))
            t += [f'{b["kode"]}. {b["teks"]}' for b in a["butir"]]
    pn = g["penutup"]
    t += [pn["perintah_pengundangan"], "Ditetapkan di Jakarta", "pada tanggal 6 Desember 2013", pn["penetapan"]["jabatan"] + ",",
          "ttd.", pn["penetapan"]["nama"], "Diundangkan di Jakarta", "pada tanggal 6 Desember 2013",
          pn["pengundangan"]["jabatan"] + ",", "ttd.", pn["pengundangan"]["nama"], pn["lembaran_negara"]]
    return "\n".join(t)


# ----------------------------------------------------------------------------- A. kualitas teks
def text_quality(gold: str, hyps: dict[str, str]) -> dict:
    ref_c, ref_w = norm(gold), toks(gold)
    out = {}
    for k, h in hyps.items():
        out[k] = {"CER_%": round(100 * jiwer.cer(ref_c, norm(h)), 1), "WER_%": round(100 * jiwer.wer(ref_w, toks(h)), 1)}
    return out


def embedded_text_layer(pdf: str) -> str:
    return "\n".join(p.get_text() for p in pymupdf.open(pdf))


def raw_ocr_text(pages: list[dict]) -> str:
    return "\n".join(l["text"] for p in pages for l in p["lines"])


# ----------------------------------------------------------------------------- B. struktur
def structure_report(chunks: list[dict], gold: dict) -> dict:
    gu = gold_units(gold)
    by_pasal = {c["pasal"]: c for c in chunks if c["chunk_type"] == "pasal"}
    by_ayat = {(c["pasal"], c["ayat"]): c for c in chunks if c["chunk_type"] == "ayat"}
    sims, bad = [], []
    for n, gtxt in gu["pasal"].items():
        c = by_pasal.get(n)
        s = fuzz.ratio(toks(gtxt), toks(c["text"])) if c else 0.0
        sims.append(s)
        if s < 97:
            bad.append((n, round(s, 1)))
    ayat_total = len(gu["ayat"])
    parsed_ayat = 0
    for (n, a), gtxt in gu["ayat"].items():
        c = by_pasal.get(n)
        if c and re.search(rf"(?m)^\({a}\)\s", c["text"]):
            parsed_ayat += 1
    return {
        "pasal_ditemukan": f"{len(by_pasal)}/{len(gu['pasal'])}",
        "ayat_terdeteksi": f"{parsed_ayat}/{ayat_total}",
        "kemiripan_teks_per_pasal_%": {"rata2": round(statistics.mean(sims), 1), "min": round(min(sims), 1),
                                       "pasal_<97%": bad},
    }


# ----------------------------------------------------------------------------- C. retrieval
STOP = set("yang dan di ke dari untuk atau pada dengan apa saja siapa berapa bagaimana adalah ini itu dalam oleh sebagai "
           "akan dapat harus wajib kepada tersebut serta juga sudah apakah bolehkah kapan mana".split())


def tok_bm25(s: str) -> list[str]:
    return [re.sub(r"(nya|lah|kah)$", "", w) for w in re.findall(r"[a-z0-9]+", s.lower()) if w not in STOP and len(w) > 1]


def naive_chunks(text: str, size: int = 500, overlap: int = 50) -> list[str]:
    """Meniru chunking karakter tetap yang memotong di tengah kata (terlihat pada keluaran aplikasi lama)."""
    step = size - overlap
    return [text[i:i + size] for i in range(0, len(text), step)]


class BM25Retriever:
    def __init__(self, docs: list[str]):
        self.docs = docs
        self.bm = BM25Okapi([tok_bm25(d) for d in docs])

    def __call__(self, q: str, k: int) -> list[str]:
        sc = self.bm.get_scores(tok_bm25(q))
        idx = sorted(range(len(sc)), key=lambda i: -sc[i])[:k]
        return [self.docs[i] for i in idx]


def evidence_hit(evidence: str, text: str, thr: int = 90) -> bool:
    return fuzz.partial_ratio(norm(evidence), norm(text)) >= thr


def eval_retrieval(search, qa: list[dict], ks=(1, 3, 5)) -> dict:
    hits = {k: 0 for k in ks}
    rows = []
    for q in qa:
        res = search(q["question"], max(ks))
        first = next((i + 1 for i, t in enumerate(res) if evidence_hit(q["evidence"], t)), None)
        for k in ks:
            hits[k] += bool(first and first <= k)
        rows.append((q["id"], first))
    n = len(qa)
    return {**{f"hit@{k}_%": round(100 * hits[k] / n, 1) for k in ks}, "peringkat_pertama": dict(rows)}


def check_evidence(qa: list[dict], gold_text: str):
    g = norm(gold_text)
    missing = [q["id"] for q in qa if norm(q["evidence"]) not in g]
    return missing


# ----------------------------------------------------------------------------- main
if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdf", required=True)
    ap.add_argument("--out", default="out")
    ap.add_argument("--gold", default="gold_perpres_76_2013.json")
    ap.add_argument("--qa", default="gold_qa.json")
    ap.add_argument("--retriever", help="modul:fungsi, signature (question:str, k:int) -> list[str] teks chunk")
    a = ap.parse_args()

    gold = json.load(open(a.gold, encoding="utf-8"))
    qa_all = json.load(open(a.qa, encoding="utf-8"))
    qa = qa_all["answerable"]
    gtext = gold_full_text(gold)
    miss = check_evidence(qa, gtext)
    assert not miss, f"evidence tidak ada di data valid: {miss}"

    pages = json.load(open(f"{a.out}/ocr_raw.json", encoding="utf-8"))
    paras = json.load(open(f"{a.out}/paragraphs_clean.json", encoding="utf-8"))
    chunks = [json.loads(l) for l in open(f"{a.out}/chunks.jsonl", encoding="utf-8")]

    emb = embedded_text_layer(a.pdf)
    report = {"A_kualitas_teks": text_quality(gtext, {
        "1_lapisan_teks_bawaan_PDF (ingest lama)": emb,
        "2_OCR_Tesseract_mentah": raw_ocr_text(pages),
        "3_pipeline_baru (bersih)": "\n".join(p["text"] for p in paras)})}
    report["B_struktur_pipeline_baru"] = structure_report(chunks, gold)

    # ---- retrieval
    indexable = [c for c in chunks if c["chunk_type"] != "visual" and not c["extra"].get("has_children")]
    text_of = {c["contextual_text"]: c for c in indexable}
    baseline = BM25Retriever(naive_chunks(emb))
    structured = BM25Retriever([c["contextual_text"] for c in indexable])
    report["C_retrieval"] = {
        "baseline_chunk_500_karakter_pada_teks_bawaan": eval_retrieval(baseline, qa),
        "pipeline_baru_chunk_per_pasal_ayat (BM25 saja)": eval_retrieval(structured, qa),
    }
    if a.retriever:
        mod, fn = a.retriever.split(":")
        report["C_retrieval"]["retriever_anda"] = eval_retrieval(getattr(importlib.import_module(mod), fn), qa)

    # ---- visual
    vis = [c for c in chunks if c["chunk_type"] == "visual"]
    vhit = 0
    for v in qa_all["visual"]:
        ok = any(c["extra"]["kind"] == v["expected_visual_kind"] and (not v.get("expected_page") or v["expected_page"] in c["extra"]["pages"]) for c in vis)
        vhit += ok
    report["D_visual"] = {"chunk_visual": len(vis), "pertanyaan_visual_punya_chunk_jawaban (cek keberadaan, bukan retrieval)": f"{vhit}/{len(qa_all['visual'])}",
                          "baseline": "0/2 (tidak ada chunk visual)"}
    print(json.dumps(report, ensure_ascii=False, indent=2))
    json.dump(report, open(f"{a.out}/eval_report.json", "w"), ensure_ascii=False, indent=2)
