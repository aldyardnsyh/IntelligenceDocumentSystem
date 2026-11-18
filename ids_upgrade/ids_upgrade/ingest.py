"""CLI ingest: PDF scan -> OCR bersih -> chunk terstruktur (+ chunk visual).

    python ingest.py --pdf Perpres_76_2013.pdf --out out \
        --title "Perpres No. 76 Tahun 2013 tentang Pengelolaan Pengaduan Pelayanan Publik" --short "Perpres 76/2013" \
        [--vlm]          # caption elemen visual + (opsional) transkripsi via Claude vision, butuh ANTHROPIC_API_KEY
"""
from __future__ import annotations

import argparse
import json
import os

from legal_chunker import build_chunks
from ocr_pipeline import process_pdf, caption_visuals_with_vlm
from text_cleaning import clean_document


def run(pdf: str, out: str, title: str, short: str, dpi: int = 300, use_vlm: bool = False):
    os.makedirs(out, exist_ok=True)
    pages = process_pdf(pdf, dpi=dpi, crop_dir=os.path.join(out, "visuals"))
    json.dump([p.to_dict() for p in pages], open(os.path.join(out, "ocr_raw.json"), "w"), ensure_ascii=False)
    visuals = [v for p in pages for v in p.visuals]
    if use_vlm:
        caption_visuals_with_vlm(visuals)
    paras, lex = clean_document(pages)
    json.dump(paras, open(os.path.join(out, "paragraphs_clean.json"), "w"), ensure_ascii=False, indent=1)
    chunks, warnings = build_chunks(paras, title, short, visuals)
    with open(os.path.join(out, "chunks.jsonl"), "w", encoding="utf-8") as f:
        for c in chunks:
            f.write(json.dumps(c.to_dict(), ensure_ascii=False) + "\n")
    json.dump({"n_pages": len(pages), "n_chunks": len(chunks), "warnings": warnings},
              open(os.path.join(out, "validation.json"), "w"), ensure_ascii=False, indent=1)
    return pages, paras, chunks, warnings


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdf", required=True)
    ap.add_argument("--out", default="out")
    ap.add_argument("--title", default="Dokumen")
    ap.add_argument("--short", default="Dokumen")
    ap.add_argument("--dpi", type=int, default=300)
    ap.add_argument("--vlm", action="store_true")
    a = ap.parse_args()
    _, _, chunks, warnings = run(a.pdf, a.out, a.title, a.short, a.dpi, a.vlm)
    print(f"{len(chunks)} chunk ditulis ke {a.out}/chunks.jsonl")
    print("Peringatan validasi:", warnings or "tidak ada")
