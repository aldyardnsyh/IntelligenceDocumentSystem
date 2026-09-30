"""Evaluasi kualitas retrieval dengan RAGAS (FR-7.3).

Skrip ini menjawab satu pertanyaan: **apakah perubahan retrieval benar-benar
membantu, atau cuma terasa lebih bagus?** Tanpa pengukuran, claims seperti
"hybrid lebih baik dari vektor saja" cuma opini.

Hasilnya ditulis ke tabel ``eval_runs``, yang dibaca endpoint
``/api/v1/analytics/summary`` dan ditampilkan di halaman /analytics.

Pakai:
    python -m scripts.evaluate_ragas --dataset evaluation/dataset.json

Lihat ``evaluation/dataset.json`` untuk formatnya.

Kenapa default provider-nya LLM: RAGAS menilai faithfulness dengan
meminta LLM lain menilai apakah jawaban benar-benar bersandar pada konteks.
Tanpa LLM, metric-nya hanya keyword overlap yang tidak mengukur apa pun tentang
hallusinasi -- persis hal yang paling ingin diukur.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path
from typing import Any

from app.core.config import get_settings
from app.providers.base import build_fallback_chain
from app.repositories.sqlite_repo import SqliteRepository, new_id, utc_now
from app.services.generation.generator import LLMChain
from app.services.ingestion.service import build_ingestion_service
from app.services.memory.store import InMemoryStore
from app.services.rag_service import RagService

logger = logging.getLogger(__name__)


def load_dataset(path: Path) -> list[dict[str, Any]]:
    """Baca dataset evaluasi dari JSON.

    Format tiap entri:
        {"question": "...", "ground_truth": "..."}

    ``ground_truth`` adalah jawaban ideal menurut dokumen. RAGAS
    membandingkan jawaban sistem terhadap ini, jadi tanpa itu yang diukur
    hanya "apakah jawaban mirip dokumen", bukan "apakah jawabannya benar".
    """
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("Dataset harus berupa JSON array.")
    for index, item in enumerate(data):
        if not item.get("question") or not item.get("ground_truth"):
            raise ValueError(
                f"Entri {index} harus punya 'question' dan 'ground_truth'."
            )
    return data


async def collect_answers(
    rag: RagService, dataset: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Jalankan pipeline untuk setiap pertanyaan dan simpan hasil lengkap.

    Konteks yang diteruskan ke RAGAS diambil dari event sitasi, bukan dari
    prompt. Yang dinilai seharusnya "apa yang sebenarnya dilihat model", bukan
    "apa yang kita karang ulang di sini" -- kalau berbeda, metriknya
    mengukur sistem yang salah.
    """
    rows: list[dict[str, Any]] = []
    for index, item in enumerate(dataset, start=1):
        question = item["question"]
        logger.info("[%d/%d] %s", index, len(dataset), question)

        answer_parts: list[str] = []
        contexts: list[str] = []
        try:
            async for event in rag.answer(question, None, item.get("document_ids")):
                if event.type == "token":
                    answer_parts.append(str(event.value))
                elif event.type == "citations":
                    contexts = [
                        f"{getattr(c, 'document_name', '')} "
                        f"chunk {getattr(c, 'chunk_index', '?')}: "
                        f"{getattr(c, 'excerpt', '')}"
                        for c in event.value  # type: ignore[union-attr]
                    ]
        except Exception:
            # Satu pertanyaan gagal tidak boleh menghentikan seluruh evaluasi;
            # hasil parsial tetap informatif dan muncul di log.
            logger.exception("Gagal menjawab: %s", question)

        rows.append(
            {
                "question": question,
                "ground_truth": item["ground_truth"],
                "answer": "".join(answer_parts),
                "contexts": contexts,
            }
        )
    return rows


def score_with_ragas(rows: list[dict[str, Any]]) -> dict[str, float | None]:
    """Hitung metric RAGAS.

    Ragas dan dependensinya bersifat opsional (`pip install -e ".[evaluation]"`).
    Kalau belum terpasang, fungsi ini mengembalikan None untuk semua metric dan
    Explain kenapa -- bukan angka placeholder yang terlihat seperti hasil
    pengukuran sungguhan.
    """
    try:
        from datasets import Dataset
        from ragas import evaluate
        from ragas.metrics import (
            answer_relevance,
            context_precision,
            faithfulness,
        )
    except ImportError:
        logger.warning(
            "RAGAS belum terpasang. Jalankan: pip install -e \".[evaluation]\""
        )
        return {"faithfulness": None, "context_precision": None, "answer_relevance": None}

    # Ragas menolak baris kosong; baris seperti itu akan gagal diam-diam
    # kalau tidak difilter lebih dulu.
    usable = [row for row in rows if row["answer"] and row["contexts"]]
    if not usable:
        logger.warning("Tidak ada baris yang bisa dinilai (jawaban atau konteks kosong).")
        return {"faithfulness": None, "context_precision": None, "answer_relevance": None}

    dataset = Dataset.from_list(
        [
            {
                "question": row["question"],
                "answer": row["answer"],
                "ground_truth": row["ground_truth"],
                "contexts": row["contexts"],
            }
            for row in usable
        ]
    )

    result = evaluate(
        dataset,
        metrics=[faithfulness, context_precision, answer_relevance],
    )

    def _value(metric_name: str) -> float | None:
        try:
            return float(result[metric_name])
        except (KeyError, TypeError, ValueError):
            return None

    return {
        "faithfulness": _value("faithfulness"),
        "context_precision": _value("context_precision"),
        "answer_relevance": _value("answer_relevance"),
    }


async def run(dataset_path: Path, *, dry_run: bool) -> int:
    settings = get_settings()

    repository: SqliteRepository
    if settings.is_sqlite_mode:
        repository = SqliteRepository(settings.sqlite_fallback_path)
    else:
        from app.repositories.supabase_repo import SupabaseRepository  # noqa: PLC0415

        repository = SupabaseRepository(settings)

    memory = InMemoryStore()
    chain = LLMChain(build_fallback_chain(settings))
    # Ingestion di sini hanya untuk membangun indeks; dokumen sudah ada dari
    # pemakaian sebelumnya.
    ingestion = build_ingestion_service(settings, repository, memory)
    rag = RagService(
        settings,
        repository,
        memory,
        ingestion.retriever,
        ingestion.embedding,
        chain,
    )

    dataset = load_dataset(dataset_path)
    rows = await collect_answers(rag, dataset)

    for row in rows:
        if not row["answer"]:
            logger.warning("Jawaban kosong untuk: %s", row["question"])

    if dry_run:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
        return 0

    scores = score_with_ragas(rows)

    if any(value is not None for value in scores.values()):
        repository.add_eval_run(
            {
                "id": new_id("eval"),
                "run_at": utc_now(),
                **scores,
            }
        )
        print(f"Skor tersimpan: {scores}")
    else:
        print("RAGAS tidak terpasang, jadi tidak ada skor yang disimpan.")
        print("Jalankan: pip install -e \".[evaluation]\"")

    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dataset",
        type=Path,
        default=Path("evaluation/dataset.json"),
        help="Berkas JSON berisi pertanyaan dan jawaban ideal.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Tampilkan jawaban dan konteks tanpa menghitung atau menyimpan skor.",
    )
    args = parser.parse_args()

    if not args.dataset.exists():
        print(f"Dataset tidak ditemukan: {args.dataset}", file=sys.stderr)
        return 1

    logging.basicConfig(
        level=logging.INFO, format="%(levelname)-8s %(message)s"
    )
    return asyncio.run(run(args.dataset, dry_run=args.dry_run))


if __name__ == "__main__":
    raise SystemExit(main())
