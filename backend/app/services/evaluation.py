"""Evaluasi retrieval berbasis hitungan sendiri, tanpa LLM dan tanpa API key.

Kenapa modul ini ada: evaluasi RAGAS butuh LLM penilai (dan API key). Tanpa
itu, halaman `/analytics` hanya menampilkan "belum ada data evaluasi" tanpa
jalan keluar, pengguna diberi tahu ada yang kurang, tapi tidak ada cara
memenuhinya.

Modul ini menghitung metrik yang bisa dijawab tanpa model:

- **Hit rate**, berapa persen pertanyaan yang menemukan sumbernya.
- **Precision@k**, dari sumber yang diambil, berapa yang memang dokumen
  yang benar.
- **Refusal benar**, berapa pertanyaan "tidak ada jawaban" yang benar-benar
  ditolak. Ini metrik paling penting: satu jawaban karangan lebih mahal
  daripada sepuluh penolakan.

Metrik ini tidak mengukur kualitas bahasa jawaban (itu tugas RAGAS), tapi
mengukur apakah retrieval menemukan dokumen yang tepat, dan itu bisa
dijalankan kapan saja, gratis, tanpa kredensial.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

#: Penanda di dataset bahwa pertanyaan ini TIDAK punya jawaban di dokumen.
NO_ANSWER_MARKERS = ("tidak ada jawaban", "no answer", "n/a")


@dataclass(slots=True)
class RetrievalEvalItem:
    """Hasil satu pertanyaan."""

    question: str
    expected_document: str | None
    retrieved_documents: list[str]
    found: bool
    refused: bool
    expected_refusal: bool


@dataclass(slots=True)
class RetrievalEvalReport:
    """Ringkasan satu run evaluasi retrieval."""

    items: list[RetrievalEvalItem] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.items)

    @property
    def answerable(self) -> list[RetrievalEvalItem]:
        return [item for item in self.items if not item.expected_refusal]

    @property
    def must_refuse(self) -> list[RetrievalEvalItem]:
        return [item for item in self.items if item.expected_refusal]

    @property
    def hit_rate(self) -> float:
        """Persentase pertanyaan yang menemukan dokumen yang benar."""
        pool = self.answerable
        if not pool:
            return 0.0
        return sum(1 for item in pool if item.found) / len(pool)

    @property
    def precision(self) -> float:
        """Dari sumber yang diambil, berapa yang memang dokumen yang benar.

        Diukur hanya pada pertanyaan yang **menyatakan** dokumen targetnya.
        Pertanyaan tanpa `document_name` tidak bisa dinilai di sini: tidak ada
        yang bisa dibandingkan, dan menghitungnya sebagai nol akan membuat
        skor terlihat buruk padahal retrieval-nya benar. Pertanyaan "tidak ada
        jawaban" dinilai terpisah lewat `refusal_rate`.
        """
        scored: list[float] = []
        for item in self.answerable:
            if item.expected_document is None:
                continue
            if not item.retrieved_documents:
                scored.append(0.0)
                continue
            benar = sum(
                1
                for name in item.retrieved_documents
                if name == item.expected_document
            )
            scored.append(benar / len(item.retrieved_documents))
        if not scored:
            return 0.0
        return sum(scored) / len(scored)

    @property
    def scored_precision_count(self) -> int:
        """Berapa pertanyaan yang ikut dinilai precision-nya."""
        return sum(
            1 for item in self.answerable if item.expected_document is not None
        )

    @property
    def refusal_rate(self) -> float:
        """Persentase pertanyaan "tidak ada jawaban" yang benar ditolak."""
        pool = self.must_refuse
        if not pool:
            return 0.0
        return sum(1 for item in pool if item.refused) / len(pool)

    @property
    def leaked(self) -> int:
        """Pertanyaan yang seharusnya ditolak tapi tetap dijawab."""
        return sum(1 for item in self.must_refuse if not item.refused)

    def summary(self) -> dict[str, object]:
        return {
            "total": self.total,
            "answerable": len(self.answerable),
            "must_refuse": len(self.must_refuse),
            "hit_rate": round(self.hit_rate, 4),
            "precision": round(self.precision, 4),
            "refusal_rate": round(self.refusal_rate, 4),
            "leaked": self.leaked,
        }


def load_dataset(path: Path) -> list[dict[str, object]]:
    """Baca golden dataset. Bentuknya sama dengan yang dipakai RAGAS."""
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("Dataset harus berupa JSON array.")
    for index, item in enumerate(data):
        if not item.get("question") or not item.get("ground_truth"):
            raise ValueError(f"Entri {index} harus punya 'question' dan 'ground_truth'.")
    return data


def expects_refusal(item: dict[str, object]) -> bool:
    """Apakah entri ini wajib dijawab "tidak ditemukan"?"""
    explicit = item.get("has_answer")
    if isinstance(explicit, bool):
        return not explicit
    truth = str(item.get("ground_truth", "")).strip().lower()
    return any(marker in truth for marker in NO_ANSWER_MARKERS)


def expected_document(item: dict[str, object]) -> str | None:
    """Dokumen yang seharusnya jadi sumber, kalau dinyatakan di dataset.

    Dataset boleh menyebut `document_name`; kalau tidak ada, penilaian
    "found" hanya melihat apakah retrieval menemukan sesuatu.
    """
    name = item.get("document_name")
    return str(name) if isinstance(name, str) and name else None