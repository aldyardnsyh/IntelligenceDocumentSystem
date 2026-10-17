"""Test reranking dua tahap.

Dua hal yang dikunci, dan keduanya adalah alasan reranking boleh ada di
aplikasi ini:

1. Reranking hanya mengubah **urutan** kandidat yang sudah lolos ambang.
   Ia tidak boleh menambah chunk yang sebelumnya ditolak ambang, karena itu
   membatalkan gerbang anti-halusinasi yang justru inti aplikasi ini.
2. Kalau reranker gagal, jawaban tetap keluar dengan urutan fusi. Reranking
   adalah peningkatan kualitas, bukan syarat agar aplikasi bisa menjawab.

Test memakai reranker tiruan, bukan model sungguhan, supaya cepat dan tidak
mengunduh 80 MB. Efek sungguhan pada kualitas diukur terpisah memakai dataset
contoh dan model asli.
"""

from __future__ import annotations

import pytest

from app.models.domain import Chunk, RetrievedChunk
from app.services.retrieval.reranker import (
    NoopReranker,
    build_reranker,
    reset_reranker,
)
from app.services.retrieval.retriever import HybridRetriever
from app.services.retrieval.vector_store import InMemoryVectorStore


class RerankerPembalik:
    """Reranker tiruan yang membalik urutan.

    Cukup untuk membuktikan bahwa urutan hasil benar-benar mengikuti
    reranker, tanpa bergantung pada isi model sungguhan.
    """

    name = "pembalik"

    def __init__(self) -> None:
        self.dipanggil = 0

    def rerank(self, question, candidates, top_k):
        self.dipanggil += 1
        urutan = list(range(len(candidates)))[::-1]
        return [(index, float(index)) for index in urutan[:top_k]]


class RerankerGagal:
    """Reranker yang selalu melempar, untuk menguji jalur cadangan."""

    name = "gagal"

    def rerank(self, question, candidates, top_k):
        raise RuntimeError("model reranker tidak tersedia")


def _chunk(nomor: int, isi: str = "isi") -> RetrievedChunk:
    return RetrievedChunk(
        chunk=Chunk(
            id=f"c{nomor}",
            document_id="d1",
            chunk_index=nomor,
            content=f"{isi} {nomor}",
            page_number=1,
        ),
        document_name="dokumen.md",
        score=1.0,
        vector_score=0.9,
        keyword_score=0.0,
    )


class TestRerankingMengubahUrutan:
    """Urutan hasil mengikuti reranker saat diaktifkan."""

    def test_urutan_mengikuti_reranker(self) -> None:
        retriever = HybridRetriever(InMemoryVectorStore(), RerankerPembalik())
        hasil = [_chunk(0), _chunk(1), _chunk(2)]

        sesudah = retriever._rerank("tanya", hasil, top_k=3)  # noqa: SLF001

        assert [item.chunk.chunk_index for item in sesudah] == [2, 1, 0]

    def test_tanpa_reranker_urutan_tidak_berubah(self) -> None:
        retriever = HybridRetriever(InMemoryVectorStore())
        hasil = [_chunk(0), _chunk(1), _chunk(2)]

        sesudah = retriever._rerank("tanya", hasil, top_k=3)  # noqa: SLF001

        assert [item.chunk.chunk_index for item in sesudah] == [0, 1, 2]

    def test_satu_hasil_tidak_perlu_rerank(self) -> None:
        """Tidak memanggil model kalau kandidatnya cuma satu."""
        pembalik = RerankerPembalik()
        retriever = HybridRetriever(InMemoryVectorStore(), pembalik)

        sesudah = retriever._rerank("tanya", [_chunk(0)], top_k=3)  # noqa: SLF001

        assert len(sesudah) == 1
        assert pembalik.dipanggil == 0, "tidak perlu memanggil model untuk satu kandidat"

    def test_hasil_kosong_tidak_error(self) -> None:
        retriever = HybridRetriever(InMemoryVectorStore(), RerankerPembalik())
        assert retriever._rerank("tanya", [], top_k=3) == []  # noqa: SLF001


class TestRerankingTidakMenambahKandidat:
    """Reranking tidak boleh menambah chunk di luar yang sudah lolos."""

    def test_jumlah_hasil_tidak_bertambah(self) -> None:
        retriever = HybridRetriever(InMemoryVectorStore(), RerankerPembalik())
        hasil = [_chunk(0), _chunk(1)]

        sesudah = retriever._rerank("tanya", hasil, top_k=10)  # noqa: SLF001

        # top_k lebih besar dari jumlah kandidat, tapi hasilnya tetap 2.
        # Pengisian paksa akan mengembalikan chunk yang tidak ada, atau
        # memaksa menambah chunk di bawah ambang.
        assert len(sesudah) == 2

    def test_top_k_lebih_kecil_dari_kandidat(self) -> None:
        retriever = HybridRetriever(InMemoryVectorStore(), RerankerPembalik())
        hasil = [_chunk(i) for i in range(5)]

        sesudah = retriever._rerank("tanya", hasil, top_k=2)  # noqa: SLF001

        assert len(sesudah) == 2

    def test_semua_item_berasal_dari_kandidat_asal(self) -> None:
        """Tidak ada objek baru yang dikarang."""
        retriever = HybridRetriever(InMemoryVectorStore(), RerankerPembalik())
        hasil = [_chunk(i) for i in range(4)]

        sesudah = retriever._rerank("tanya", hasil, top_k=4)  # noqa: SLF001

        for item in sesudah:
            assert any(item is asal for asal in hasil)


class TestRerankerGagalTetapMenjawab:
    """Kegagalan reranker tidak boleh menggagalkan jawaban."""

    def test_kembali_ke_urutan_fusi(self) -> None:
        retriever = HybridRetriever(InMemoryVectorStore(), RerankerGagal())
        hasil = [_chunk(0), _chunk(1), _chunk(2)]

        sesudah = retriever._rerank("tanya", hasil, top_k=3)  # noqa: SLF001

        # Urutan asli dipertahankan, bukan kosong.
        assert [item.chunk.chunk_index for item in sesudah] == [0, 1, 2]


class TestPembangunanReranker:
    """Pemilihan reranker mengikuti konfigurasi."""

    def test_default_mati(self, settings) -> None:
        assert settings.rerank_enabled is False

    def test_mati_menghasilkan_noop(self) -> None:
        reset_reranker()
        reranker = build_reranker(enabled=False, model_name="apa-saja")
        assert isinstance(reranker, NoopReranker)

    def test_noop_tidak_mengubah_urutan(self) -> None:
        noop = NoopReranker()
        hasil = noop.rerank("tanya", ["a", "b", "c"], 3)
        assert [index for index, _ in hasil] == [0, 1, 2]

    def test_gagal_memuat_model_jatuh_ke_noop(self) -> None:
        """Nama model yang tidak ada tidak boleh menggagalkan aplikasi.

        Aplikasi yang jalan tanpa reranking lebih berguna daripada yang tidak
        bisa start karena model gagal diunduh.
        """
        reset_reranker()
        reranker = build_reranker(
            enabled=True, model_name="model/yang-tidak-pernah-ada-xyz"
        )
        assert isinstance(reranker, NoopReranker)
        reset_reranker()


class TestKonfigurasiRerank:
    """Nilai konfigurasi masuk akal."""

    def test_jumlah_kandidat_wajar(self, settings) -> None:
        assert settings.rerank_candidates >= 2

    def test_model_default(self, settings) -> None:
        assert "cross-encoder" in settings.rerank_model
