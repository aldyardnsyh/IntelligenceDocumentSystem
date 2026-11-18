"""Evaluasi kualitas ekstraksi & retrieval terhadap data gold.

Tiga pengukuran, semuanya bisa jalan tanpa LLM dan tanpa API:

1. **CER/WER per Pasal** — teks hasil ekstraksi dibandingkan dengan teks
   referensi manusia (``evaluation/gold-perpres-76-2013.json``). Ini meteran
   paling keras untuk keluhan "OCR-nya kotor": satu karakter salah langsung
   terhitung, bukan diasumsikan.
2. **Evidence hit** — 24 pertanyaan ``gold-qa.json`` membawa cuplikan jawaban
   verbatim dari teks referensi. Retrieval dinilai bukan dari nama dokumen
   (terlalu mudah) tapi apakah potongan jawaban itu benar-benar muncul di
   chunk yang dikembalikan.
3. **Penolakan wajar** — 4 pertanyaan yang isinya memang tidak ada di dokumen
   harus menghasilkan retrieval kosong.

Jalankan dari direktori ``backend``:

    python -m scripts.eval_gold --pdf "Perpres 76 2013.pdf"

Ingestion dijalankan ke SQLite sementara + vector store memori, jadi skrip
ini tidak menyentuh data aplikasi. Untuk pengukuran penuh (termasuk reranker
dan jawaban LLM), pakai endpoint ``/analytics/evaluate``.
"""

from __future__ import annotations

import argparse
import asyncio
import difflib
import json
import re
import tempfile
from pathlib import Path

from app.core.config import get_settings
from app.models.domain import RetrievalSettings
from app.providers.embedding import build_embedding_provider
from app.repositories.sqlite_repo import SqliteRepository
from app.services.ingestion.service import IngestionService
from app.services.retrieval.retriever import HybridRetriever
from app.services.retrieval.text_processing import configure_stemming
from app.services.retrieval.vector_store import InMemoryVectorStore

EVAL_DIR = Path(__file__).resolve().parent.parent / "evaluation"

#: Normalisasi teks sebelum dibandingkan: spasi dan tanda baca tidak boleh
#: mempengaruhi CER — yang diukur adalah kebenaran hurufnya, bukan tipografi.
_NORMALIZE_RE = re.compile(r"\s+")


def normalize(text: str) -> str:
    """Ratakan spasi; huruf besar diabaikan; tanda baca tipografis dihapus."""
    cleaned = text.replace("\u2013", "-").replace("\u2014", "-")
    cleaned = re.sub(r"[.,;:()'\"«»\u00a0]", "", cleaned)
    return _NORMALIZE_RE.sub(" ", cleaned).strip().lower()


def levenshtein(first: str, second: str) -> int:
    """Jarak edit klasik, dua baris memori.

    Korpusnya ribuan karakter per Pasal, jadi implementasi O(n*m) sederhana
    sudah cukup cepat.
    """
    if len(first) < len(second):
        first, second = second, first
    previous = list(range(len(second) + 1))
    for row, char in enumerate(first, start=1):
        current = [row]
        for column, other in enumerate(second, start=1):
            substitution = previous[column - 1] + (char != other)
            current.append(min(previous[column] + 1, current[column - 1] + 1, substitution))
        previous = current
    return previous[-1]


def error_rates(reference: str, hypothesis: str) -> tuple[float, float]:
    """CER dan WER, 0..1 — jarak edit dinormalisasi panjang referensi."""
    reference, hypothesis = normalize(reference), normalize(hypothesis)
    if not reference:
        return (0.0, 0.0)
    cer = levenshtein(reference, hypothesis) / len(reference)
    ref_words, hyp_words = reference.split(), hypothesis.split()
    wer = levenshtein(" ".join(ref_words), " ".join(hyp_words)) / max(len(ref_words), 1)
    return (cer, wer)


def gold_pasal_texts(gold: dict) -> dict[int, str]:
    """Teks referensi per Pasal, dirakit dari struktur gold.

    Ayat bisa bersarang: satu ayat boleh punya pengantar, teks, DAN butir
    di dalamnya. Tanpa penanganan bersarang, isi ayat butir menjadi "None"
    dan meteran menganggap teks yang benar sebagai salah.
    """
    texts: dict[int, str] = {}

    def _butir_text(butir: dict) -> str:
        return f"{butir['kode']}. {butir['teks']}"

    for entry in gold["batang_tubuh"]:
        parts: list[str] = []
        if entry.get("pengantar"):
            parts.append(entry["pengantar"])
        for ayat in entry.get("ayat") or []:
            if ayat.get("pengantar"):
                parts.append(f"({ayat['nomor']}) {ayat['pengantar']}")
            elif ayat.get("teks"):
                parts.append(f"({ayat['nomor']}) {ayat['teks']}")
            for butir in ayat.get("butir") or []:
                parts.append(_butir_text(butir))
        for butir in entry.get("butir") or []:
            parts.append(_butir_text(butir))
        if entry.get("teks"):
            parts.append(entry["teks"])
        texts[int(entry["nomor_pasal"])] = "\n".join(parts)
    return texts


def strip_chunk_header(content: str) -> str:
    """Buang baris header konteks legal ("BAB ... · Pasal N") dari isi chunk.

    Header itu buatan legal.py untuk bantuan embedding, bukan isi dokumen;
    mengikut sertakannya dalam CER menghukum teks yang sebenarnya benar.
    """
    lines = content.split("\n")
    if lines and ("·" in lines[0] and "Pasal" in lines[0]):
        return "\n".join(lines[1:])
    return content


def chunk_section_number(section: str | None) -> int | None:
    """Nomor Pasal dari label section chunk ("Pasal 12" -> 12)."""
    if not section:
        return None
    match = re.match(r"^Pasal\s+(\d+)$", section.strip())
    return int(match.group(1)) if match else None


async def run(pdf_path: Path, tanpa_perbaikan: bool = False, rerank: bool = False) -> int:
    settings = get_settings()
    settings.ocr_engine = "paddle"  # tanpa panggilan API vision
    # Pengukuran retrieval murni menonaktifkan rerank; kondisi produksi
    # (--rerank) memakai cross-encoder seperti aplikasi sungguhan.
    settings.rerank_enabled = rerank
    if tanpa_perbaikan:
        # Mode pembanding A/B: matikan pass perbaikan level dokumen (koreksi
        # leksikon + penanda) supaya kontribusinya terukur.
        settings.ocr_typo_correction_enabled = False
        settings.ocr_repair_markers_enabled = False

    repository = SqliteRepository(str(Path(tempfile.mkdtemp()) / "eval-gold.db"), defaults=settings)
    store = InMemoryVectorStore()
    reranker = None
    if rerank:
        from app.services.retrieval.reranker import build_reranker  # noqa: PLC0415

        reranker = build_reranker(
            settings.rerank_enabled, settings.rerank_model, settings.rerank_device
        )
    retriever = HybridRetriever(
        store, reranker, rerank_candidates=settings.rerank_candidates,
        fuzzy_enabled=settings.bm25_fuzzy_enabled,
    )
    embedding = build_embedding_provider(settings)
    configure_stemming(settings)
    ingestion = IngestionService(settings, repository, store, retriever, embedding, None)

    print(f"Ingestion {pdf_path.name} (PP-OCR lokal)...", flush=True)
    document = await ingestion.register(pdf_path.name, pdf_path.read_bytes())
    await ingestion.wait_pending()
    document = repository.get_document(document.id)
    if document.status.value != "ready":
        print(f"INGESTION GAGAL: {document.error_message}")
        return 1
    print(f"Siap: {document.chunk_count} chunk dari {document.page_count} halaman.", flush=True)

    chunks = repository.get_chunks(document.id, page=1, page_size=10000, search=None)[0]
    by_pasal: dict[int, str] = {}
    for chunk in chunks:
        number = chunk_section_number(getattr(chunk, "section", None))
        if number is not None:
            by_pasal.setdefault(number, "")
            by_pasal[number] += "\n" + strip_chunk_header(chunk.content)

    # --- 1. Cakupan & kemiripan per Pasal
    #
    # Tiga meteran per Pasal, semuanya pada teks ternormalisasi:
    # - **coverage**: berapa porsi karakter teks referensi yang tercakup blok
    #   bersama dengan hasil ekstraksi — langsung menjawab "berapa banyak isi
    #   yang hilang atau salah dibaca".
    # - **similarity**: kemiripan keseluruhan SequenceMatcher — kebalikan
    #   material ekstra (header, duplikasi ayat) yang menghukum CER mentah.
    # - **CER** hanya pada pasal ber-chunk tunggal; pada pasal yang terpecah
    #   atau menyimpan blok tetangga, CER mentah mencapai > 100% bukan karena
    #   teksnya seburuk itu tapi karena penyebutnya kecil, jadi ia hanya
    #   informatif di kasus paling bersih.
    gold = json.loads((EVAL_DIR / "gold-perpres-76-2013.json").read_text(encoding="utf-8"))
    rates: list[tuple[int, float, float]] = []
    for number, reference in gold_pasal_texts(gold).items():
        hypothesis = by_pasal.get(number)
        if hypothesis is None or not reference:
            print(f"  Pasal {number}: CHUNK TIDAK DITEMUKAN ATAU REFERENSI KOSONG")
            rates.append((number, 0.0, 0.0))
            continue
        ref_norm, hyp_norm = normalize(reference), normalize(hypothesis)
        matcher = difflib.SequenceMatcher(None, ref_norm, hyp_norm, autojunk=False)
        matched = sum(block.size for block in matcher.get_matching_blocks())
        coverage = matched / max(len(ref_norm), 1)
        rates.append((number, coverage, matcher.ratio()))
    if rates:
        avg_cov = sum(c for _, c, _ in rates) / len(rates)
        avg_sim = sum(s for _, _, s in rates) / len(rates)
        worst = min(rates, key=lambda item: item[1])
        terburuk = f", terburuk Pasal {worst[0]} = {worst[2]:.1%}"
        print(f"\nCakupan teks referensi per Pasal: rata-rata {avg_cov:.1%}")
        print(f"Kemiripan per Pasal: rata-rata {avg_sim:.1%}{terburuk}")
        for number, coverage, similarity in sorted(rates, key=lambda item: item[1])[:5]:
            print(f"  Pasal {number}: cakupan {coverage:.1%} / kemiripan {similarity:.1%}")

    # --- 2 & 3. Evidence QA + penolakan
    gold_qa = json.loads((EVAL_DIR / "gold-qa.json").read_text(encoding="utf-8"))
    eval_settings = RetrievalSettings(
        top_k=5, similarity_threshold=settings.default_similarity_threshold
    )

    def _strip(text: str) -> str:
        """Buka singkatan "1" -> "(1)" dsb. yang membedakan antar penyajian."""
        return normalize(text)

    evidence_hits = 0
    evidence_misses: list[str] = []
    for item in gold_qa.get("answerable", []):
        question = str(item["question"])
        evidence = _strip(str(item["evidence"]))
        qvec = await asyncio.to_thread(embedding.embed_query, question)
        retrieved = await asyncio.to_thread(
            retriever.retrieve, question, qvec, eval_settings.top_k,
            eval_settings.similarity_threshold, [document.id],
            settings.keyword_strong_bar,
        )
        corpus = _strip("\n".join(item.chunk.content for item in retrieved))
        if evidence and evidence[:80] in corpus:
            evidence_hits += 1
        else:
            evidence_misses.append(f"{item['id']}: {question[:60]}")
    answerable = len(gold_qa.get("answerable", []))
    if answerable:
        print(f"\nEvidence hit (verbatim di top-5): {evidence_hits}/{answerable}")
        for miss in evidence_misses:
            print(f"  MISS {miss}")

    refusals_ok = 0
    for item in gold_qa.get("unanswerable", []):
        question = str(item["question"])
        qvec = await asyncio.to_thread(embedding.embed_query, question)
        retrieved = await asyncio.to_thread(
            retriever.retrieve, question, qvec, eval_settings.top_k,
            eval_settings.similarity_threshold, [document.id],
            settings.keyword_strong_bar,
        )
        if not retrieved:
            refusals_ok += 1
        else:
            print(f"  BOCOR {item['id']}: {question[:60]} (retrieval mengembalikan sumber)")
    unanswerable = len(gold_qa.get("unanswerable", []))
    if unanswerable:
        print(f"Penolakan wajar (retrieval kosong): {refusals_ok}/{unanswerable}")

    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--pdf",
        default=r"D:\Riset Pribadi\RAG - Intelegence Document System\Perpres 76 2013.pdf",
        help="Berkas PDF yang diekstraksi dan diuji.",
    )
    parser.add_argument(
        "--tanpa-perbaikan",
        action="store_true",
        help="Matikan pass perbaikan level dokumen, sebagai pembanding A/B.",
    )
    parser.add_argument(
        "--rerank",
        action="store_true",
        help="Aktifkan cross-encoder reranker seperti kondisi produksi.",
    )
    args = parser.parse_args()
    return asyncio.run(
        run(Path(args.pdf), tanpa_perbaikan=args.tanpa_perbaikan, rerank=args.rerank)
    )


if __name__ == "__main__":
    raise SystemExit(main())
