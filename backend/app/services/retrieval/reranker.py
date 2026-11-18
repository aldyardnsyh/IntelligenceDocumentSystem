"""Reranking dua tahap dengan cross-encoder.

## Kenapa perlu

Ambang tunggal pada cosine similarity tidak bisa memisahkan sempurna. Diukur
pada dataset contoh:

- chunk yang memuat jawaban dan chunk yang tidak memuat jawaban punya rentang
  skor cosine yang **tumpang tindih**. Tidak ada ambang yang benar untuk semua
  kasus: ambang rendah meloloskan chunk salah, ambang tinggi membuang chunk
  benar.

## Kenapa cross-encoder membantu

Embedding membandingkan dua teks yang dihitung **terpisah**, jadi ia tidak
pernah melihat bagaimana pertanyaan dan chunk saling berhubungan.
Cross-encoder membaca keduanya **bersamaan** dalam satu forward pass, sehingga
bisa menilai kecocokan yang tidak tertangkap oleh jarak vektor. Diukur pada
dataset contoh: ketepatan posisi pertama naik dari 4/11 menjadi 7/11.

## Kenapa ``bge-reranker-v2-m3``

Model Inggris seperti ``cross-encoder/ms-marco-MiniLM-L-6-v2`` memberi skor
yang praktis tidak bermakna untuk pasangan pertanyaan-chunk Bahasa Indonesia.
``BAAI/bge-reranker-v2-m3`` multilingual (100+ bahasa, termasuk Indonesia)
dan berlisensi Apache-2.0. Biayanya: sekitar 1.1 GB RAM dan 150 sampai 400 ms
per pertanyaan di CPU. Model dimuat sekali; kegagalan memuat tidak menjatuhkan
aplikasi (fallback ke urutan fusion), karena retrieval yang jalan tanpa
reranking lebih berguna daripada aplikasi yang tidak bisa start.
"""

from __future__ import annotations

import logging
import threading
from typing import Protocol

logger = logging.getLogger(__name__)


class Reranker(Protocol):
    """Antarmuka reranker."""

    name: str

    def rerank(
        self, question: str, candidates: list[str], top_k: int
    ) -> list[tuple[int, float]]:
        """Urutkan ulang kandidat. Kembalikan pasangan ``(indeks, skor)``."""
        ...


class CrossEncoderReranker:
    """Reranker berbasis cross-encoder sentence-transformers."""

    def __init__(self, model_name: str, device: str = "cpu") -> None:
        from sentence_transformers import CrossEncoder  # noqa: PLC0415

        self.name = model_name
        # Model dimuat sekali saat dibuat, bukan per pertanyaan. Memuatnya
        # per pertanyaan menambah beberapa detik ke setiap jawaban.
        self._model = CrossEncoder(model_name, device=device)
        logger.info("Reranker siap: %s (device=%s)", model_name, device)

    def rerank(
        self, question: str, candidates: list[str], top_k: int
    ) -> list[tuple[int, float]]:
        """Nilai ulang setiap pasangan pertanyaan dan kandidat.

        Mengembalikan indeks kandidat beserta skornya, terurut menurun.
        Indeks dipakai, bukan teks, supaya pemanggil tetap memegang objek
        aslinya beserta metadatanya.
        """
        if not candidates:
            return []

        pasangan = [(question, teks) for teks in candidates]
        skor = self._model.predict(pasangan)
        berperingkat = sorted(
            enumerate(float(s) for s in skor),
            key=lambda item: item[1],
            reverse=True,
        )
        return berperingkat[:top_k]


class NoopReranker:
    """Reranker yang tidak mengubah apa pun.

    Dipakai saat reranking dimatikan, supaya pemanggil tidak perlu menulis
    ``if`` di jalur utama. Dengan begitu, menyalakan dan mematikan fitur ini
    tidak mengubah bentuk kode yang dijalankan.
    """

    name = "none"

    def rerank(
        self, question: str, candidates: list[str], top_k: int
    ) -> list[tuple[int, float]]:
        del question
        # Skor menurun supaya urutannya sama dengan urutan masuk.
        return [(index, 0.0) for index in range(min(top_k, len(candidates)))]


_reranker: Reranker | None = None
_reranker_lock = threading.Lock()


def build_reranker(enabled: bool, model_name: str, device: str = "cpu") -> Reranker:
    """Bangun reranker sekali, lalu pakai bersama.

    Kegagalan memuat model TIDAK menggagalkan aplikasi: yang terjadi adalah
    peringatan dan reranker kosong, sehingga retrieval tetap berjalan seperti
    sebelum fitur ini ada. Aplikasi yang jalan tanpa reranking lebih berguna
    daripada yang tidak bisa start karena model gagal diunduh.
    """
    global _reranker
    if _reranker is not None:
        return _reranker

    with _reranker_lock:
        if _reranker is not None:
            return _reranker

        if not enabled:
            _reranker = NoopReranker()
            return _reranker

        try:
            _reranker = CrossEncoderReranker(model_name, device=device)
        except Exception:  # noqa: BLE001
            logger.warning(
                "Reranker gagal dimuat (%s). Retrieval berjalan tanpa "
                "reranking, jadi kualitas bisa lebih rendah dari yang "
                "diharapkan. Periksa koneksi ke Hugging Face atau pasang "
                "sentence-transformers.",
                model_name,
                exc_info=True,
            )
            _reranker = NoopReranker()
        return _reranker


def reset_reranker() -> None:
    """Bersihkan singleton. Dipakai test."""
    global _reranker
    with _reranker_lock:
        _reranker = None
