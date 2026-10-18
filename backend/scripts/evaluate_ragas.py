"""Evaluasi kualitas retrieval dengan RAGAS.

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
hallusinasi, persis hal yang paling ingin diukur.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import shutil
import sys
from pathlib import Path
from typing import Any

from app.core.config import get_settings
from app.dependencies import _index_entries
from app.providers.base import build_fallback_chain
from app.repositories.sqlite_repo import SqliteRepository, new_id, utc_now
from app.services.evaluation_evaluator import OfflineEvaluator
from app.services.generation.generator import LLMChain
from app.services.ingestion.service import IngestionService, build_ingestion_service
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
    "apa yang kita karang ulang di sini", kalau berbeda, metriknya
    mengukur sistem yang salah.
    """
    rows: list[dict[str, Any]] = []
    for index, item in enumerate(dataset, start=1):
        question = item["question"]
        logger.info("[%d/%d] %s", index, len(dataset), question)

        answer_parts: list[str] = []
        contexts: list[str] = []
        not_found = False
        try:
            async for event in rag.answer(question, None, item.get("document_ids")):
                if event.type == "token":
                    answer_parts.append(str(event.value))
                elif event.type == "not_found":
                    not_found = True
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
                # Penolakan menjawab adalah perilaku yang harus dinilai, jadi
                # jawaban "tidak ditemukan" ikut disimpan utuh. Versi lama
                # mengambil nilai dari `value` yang tidak ada di event ini
                # sehingga barisnya selalu kosong.
                "answer": "".join(answer_parts),
                "contexts": contexts,
                # Label dataset: TIDAK ADA JAWABAN berarti sistem wajib
                # menjawab "tidak ditemukan".
                "expect_not_found": _expects_not_found(item),
                "not_found": not_found,
            }
        )
    return rows


#: Nilai `ground_truth` yang menandai pertanyaan tanpa jawaban.
_NO_ANSWER_MARKERS = ("tidak ada", "no answer", "n/a")


def _expects_not_found(item: dict[str, Any]) -> bool:
    """Apakah pertanyaan ini wajib dijawab "tidak ditemukan"?

    Label eksplisit di dataset selalu menang. Tanpa itu, pencocokan teks
    `ground_truth` dipakai sebagai cadangan, dan pencocokan substring
    menyesatkan: jawaban sah yang diawali "Tidak ada bukti bahwa..." akan
    ikut terklasifikasi sebagai kasus tanpa jawaban, lalu dibuang dari skor.
    """
    explicit = item.get("has_answer")
    if isinstance(explicit, bool):
        return not explicit
    truth = str(item.get("ground_truth", "")).strip().lower()
    return any(marker in truth for marker in _NO_ANSWER_MARKERS)


def report_refusal(rows: list[dict[str, Any]]) -> dict[str, int]:
    """Hitung seberapa sering sistem menolak menjawab dengan benar.

    Ini metrik yang paling penting di sistem ini, dan selama ini tidak pernah
    dihitung: baris "harus tidak ditemukan" justru dibuang dari skor RAGAS
    karena konteksnya kosong, sehingga kemampuan menolak menjawab, kemampuan
    yang paling menentukan apakah sistem boleh dipercaya, tidak pernah
    tervalidasi.
    """
    summary = {"expected": 0, "refused": 0, "leaked": 0}
    for row in rows:
        if not row.get("expect_not_found"):
            continue
        summary["expected"] += 1
        if row.get("not_found"):
            summary["refused"] += 1
        else:
            summary["leaked"] += 1
    return summary


def score_with_ragas(
    rows: list[dict[str, Any]], *, offline: bool = False
) -> dict[str, float | None]:
    """Hitung metric RAGAS.

    Ragas dan dependensinya bersifat opsional (`pip install -e ".[evaluation]"`).
    Kalau belum terpasang, fungsi ini mengembalikan None untuk semua metric dan
    Explain kenapa, bukan angka placeholder yang terlihat seperti hasil
    pengukuran sungguhan.
    """
    try:
        from datasets import Dataset
        from ragas import evaluate
        from ragas.metrics import (
            answer_relevancy,
            context_precision,
            faithfulness,
        )
    except ImportError as exc:
        logger.warning(
            "RAGAS belum terpasang atau versinya tidak cocok (%s). "
            "Jalankan: pip install -e \".[evaluation]\"",
            exc,
        )
        return {"faithfulness": None, "precision": None, "answer_relevance": None}

    # Ragas menolak baris kosong; baris seperti itu akan gagal diam-diam
    # kalau tidak difilter lebih dulu. Baris "tidak ditemukan" juga dikecualikan
    # di sini, tidak ada konteks untuk dinilai, dan ketidakhadirannya sudah
    # dihitung lewat `report_refusal`.
    usable = [
        row
        for row in rows
        if row["answer"] and row["contexts"] and not row.get("expect_not_found")
    ]
    if not usable:
        logger.warning("Tidak ada baris yang bisa dinilai (jawaban atau konteks kosong).")
        return {"faithfulness": None, "precision": None, "answer_relevance": None}

    dataset = Dataset.from_list(
        [
            {
                # Ragas 0.2 mengganti nama kolomnya. Skrip ini dipasang lewat
                # `pip install -e ".[evaluation]"` yang mengikat versi
                # terbaru, jadi nama lama hanya menghasilkan KeyError yang
                # tidak menjelaskan apa pun.
                "user_input": row["question"],
                "response": row["answer"],
                "reference": row["ground_truth"],
                "retrieved_contexts": row["contexts"],
                # Kolom lama tetap diisi agar Ragas versi 0.1 (jika terpasang)
                # tidak langsung menolak barisnya.
                "question": row["question"],
                "answer": row["answer"],
                "ground_truth": row["ground_truth"],
                "contexts": row["contexts"],
            }
            for row in usable
        ]
    )

    # Mode offline memakai penilai tiruan yang deterministik. Tujuannya bukan
    # mengukur kualitas jawaban, melainkan membuktikan seluruh pipa RAGAS
    # berjalan tanpa API key: dataset terbentuk, metrik dihitung, dan skor
    # terbaca kembali. Tanpa mode ini, jalur tersebut tidak pernah dijalankan
    # sampai ada orang yang membayar token.
    penilai = OfflineEvaluator() if offline else None
    opsi: dict[str, Any] = {}
    if penilai is not None:
        opsi["llm"] = penilai
        opsi["embeddings"] = penilai

    try:
        result = evaluate(
            dataset,
            metrics=[faithfulness, context_precision, answer_relevancy],
            **opsi,
        )
    except Exception:  # noqa: BLE001
        # Kegagalan di dalam Ragas (LLM evaluator tidak dikonfigurasi,
        # versi tidak cocok, API error) harus muncul sebagai pesan, bukan
        # traceback yang membuat pengguna mengira sistemnya yang rusak.
        logger.exception("RAGAS gagal dijalankan.")
        print(
            "RAGAS gagal dijalankan. Penyebab paling umum: LLM evaluator belum "
            "dikonfigurasi (set OPENAI_API_KEY atau LLM_API_KEY sesuai versi "
            "ragas yang terpasang).",
            file=sys.stderr,
        )
        return {"faithfulness": None, "precision": None, "answer_relevance": None}

    def _rata_rata(nilai: list[float]) -> float | None:
        # NaN muncul saat RAGAS tidak punya cukup bahan menilai satu baris.
        # NaN bukan skor: menyimpannya membuat kolom terisi angka yang tidak
        # bisa dibandingkan, jadi baris seperti itu dibuang.
        bersih = [item for item in nilai if item == item]
        if not bersih:
            return None
        return round(sum(bersih) / len(bersih), 4)

    def _dari_scores(metric_name: str) -> list[float]:
        """Ambil nilai satu metrik dari `result.scores`.

        `scores` adalah daftar dict, satu per baris dataset. Nilai `None` dan
        `NaN` (baris yang gagal dinilai) dilewati, bukan dihitung sebagai nol:
        nol berarti "skornya nol", yang berbeda dari "tidak bisa dinilai".
        """
        kumpulan: list[float] = []
        scores = getattr(result, "scores", None) or []
        for baris in scores:
            if not isinstance(baris, dict):
                continue
            nilai = baris.get(metric_name)
            try:
                kumpulan.append(float(nilai))
            except (TypeError, ValueError):
                continue
        return kumpulan

    def _dari_pandas(metric_name: str) -> list[float]:
        """Cadangan: baca dari DataFrame bila `scores` tidak tersedia."""
        kumpulan: list[float] = []
        try:
            tabel = result.to_pandas()
        except Exception:  # noqa: BLE001
            return kumpulan
        if metric_name not in tabel.columns:
            return kumpulan
        for nilai in tabel[metric_name].tolist():
            try:
                kumpulan.append(float(nilai))
            except (TypeError, ValueError):
                continue
        return kumpulan

    def _value(metric_name: str) -> float | None:
        nilai = _dari_scores(metric_name)
        if not nilai:
            nilai = _dari_pandas(metric_name)
        return _rata_rata(nilai)

    return {
        "faithfulness": _value("faithfulness"),
        # `context_precision` disimpan ke kolom `precision`. Versi lama
        # mengirim key `context_precision` apa adanya, sementara repository
        # membaca `run.get("precision")`, jadi kolomnya selalu NULL dan
        # metrik retrieval yang paling relevan tidak pernah muncul di analitik.
        "precision": _value("context_precision"),
        "answer_relevance": _value("answer_relevancy"),
    }


def _evaluation_repository(settings: object) -> SqliteRepository:
    """Repository sementara berisi salinan database aplikasi.

    Evaluasi menjawab setiap pertanyaan dataset melalui pipeline penuh, dan
    pipeline itu memang menulis sesi serta log query. Kalau itu terjadi di
    database yang sedang dipakai aplikasi, satu run evaluasi mengisi sidebar
    dengan puluhan sesi palsu dan mengotori analitik pengguna.

    Karena itu database produksi disalin ke berkas sementara lebih dulu.
    Kegagalan membaca corpus berarti tidak ada yang bisa dinilai, jadi
    menyalin lebih baik daripada menulis ke data yang salah.
    """
    source = Path(settings.sqlite_fallback_path)  # type: ignore[attr-defined]
    if not source.exists():
        raise SystemExit(
            f"Database tidak ditemukan: {source}. Jalankan `python -m scripts.seed_demo` dulu."
        )
    target = source.with_name(source.stem + ".evaluasi.db")
    shutil.copy2(source, target)
    logger.info("Evaluasi memakai salinan database: %s", target)
    return SqliteRepository(str(target))


def _rebuild_index(ingestion: IngestionService, repository: SqliteRepository) -> int:
    """Bangun ulang indeks retrieval dari metadata yang sudah tersimpan.

    Fungsi sinkron karena dipanggil lewat ``asyncio.to_thread``: I/O SQLite
    dan iterasi BM25 cukup berat untuk memblokir event loop.
    """
    return ingestion.retriever.rebuild(_index_entries(repository))


async def run(dataset_path: Path, *, dry_run: bool, offline: bool = False) -> int:
    settings = get_settings()

    # Evaluasi memakai salinan database, bukan database yang sedang dipakai
    # aplikasi. Satu run menulis sesi dan query log untuk setiap pertanyaan;
# kalau ditulis langsung ke DB produksi, sidebar pengguna terisi puluhan sesi
    # palsu dan tabel analitik ikut tercemar.
    repository = _evaluation_repository(settings)

    memory = InMemoryStore()
    chain = LLMChain(build_fallback_chain(settings), max_retries=settings.llm_max_retries)
    # Ingestion di sini hanya untuk membangun indeks; dokumen sudah ada dari
    # pemakaian sebelumnya.
    ingestion = build_ingestion_service(settings, repository, memory)

    # Indeks kata dan metadata chunk harus dibangun ulang dari metadata yang
    # tersimpan. Tanpa ini `retrieve()` membuang semua hit vektor yang
    # entry-nya kosong, jadi seluruh baris evaluasi dijawab "tidak ditemukan"
    # tanpa satu pun error yang menunjuk penyebabnya.
    rebuilt = await asyncio.to_thread(_rebuild_index, ingestion, repository)
    logger.info("Indeks retrieval dipulihkan: %d chunk.", rebuilt)

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

    refusal = report_refusal(rows)
    if refusal["expected"]:
        print(
            "Penolakan menjawab: "
            f"{refusal['refused']}/{refusal['expected']} ditolak dengan benar, "
            f"{refusal['leaked']} justru dijawab."
        )
    else:
        print("Dataset tidak memuat pertanyaan 'tidak ada jawaban'.")

    if dry_run:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
        return 0

    scores = score_with_ragas(rows, offline=offline)

    if offline and any(value is not None for value in scores.values()):
        # Skor offline mengukur kesamaan kata, bukan kesetiaan jawaban pada
        # konteks. Menyimpannya ke `eval_runs` akan membuat halaman analitik
        # menampilkan angka yang terlihat seperti hasil pengukuran, padahal
        # bukan. Jadi dicetak saja.
        print(f"Skor mode offline (bukan ukuran kualitas): {scores}")
    elif any(value is not None for value in scores.values()):
        repository.add_eval_run(
            {
                "id": new_id("eval"),
                "run_at": utc_now(),
                **scores,
            }
        )
        print(f"Skor tersimpan: {scores}")
    else:
        print("RAGAS tidak terpasang atau tidak bisa dipakai, jadi tidak ada skor.")
        print("Jalankan: pip install -e \".[evaluation]\"")
        print("RAGAS juga butuh evaluator LLM/embedding sendiri (mis. OPENAI_API_KEY).")

    # Penolakan menjawab adalah kegagalan paling mahal di sistem ini, jadi
    # kemunculannya yang menentukan exit code, bukan skor yang tidak pernah
    # dihitung.
    if refusal["leaked"]:
        print(
            f"PERINGATAN: {refusal['leaked']} pertanyaan tanpa jawaban tetap dijawab. "
            "Artinya sistem mengarang saat tidak tahu.",
            file=sys.stderr,
        )
        return 1
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
    parser.add_argument(
        "--offline",
        action="store_true",
        help=(
            "Hitung skor dengan penilai tiruan, tanpa API key dan tanpa jaringan. "
            "Berguna untuk memeriksa bahwa pipa evaluasi berjalan. Skornya BUKAN "
            "ukuran kualitas jawaban, dan tidak disimpan ke database."
        ),
    )
    args = parser.parse_args()

    if not args.dataset.exists():
        print(f"Dataset tidak ditemukan: {args.dataset}", file=sys.stderr)
        return 1

    logging.basicConfig(
        level=logging.INFO, format="%(levelname)-8s %(message)s"
    )
    return asyncio.run(run(args.dataset, dry_run=args.dry_run, offline=args.offline))


if __name__ == "__main__":
    raise SystemExit(main())
