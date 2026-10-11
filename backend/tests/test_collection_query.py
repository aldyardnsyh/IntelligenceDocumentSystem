"""Test deteksi pertanyaan koleksi dan pencocokan topik.

Yang dijaga di sini: pertanyaan tentang daftar dokumen tidak boleh jatuh ke
mode pengetahuan umum. Itu jalur halusinasi paling berbahaya, karena model
menyusun daftar buku dengan penulis, tahun, dan URL yang tidak ada, dan
hasilnya terlihat kredibel.
"""

from __future__ import annotations

import pytest

from app.services.collection_query import (
    is_collection_question,
    matches_topic,
    topic_terms,
)


class TestDeteksiPertanyaanKoleksi:
    @pytest.mark.parametrize(
        "question",
        [
            "carikan dokumen terkait dengan tiketing",
            "carikan dokumen tentang cuti",
            "dokumen apa saja yang tersedia?",
            "ada berapa dokumen?",
            "daftar dokumen",
            "dokumen tentang tiket",
            "apa saja berkas yang ada",
        ],
    )
    def test_pertanyaan_koleksi_terdeteksi(self, question: str) -> None:
        assert is_collection_question(question) is True

    @pytest.mark.parametrize(
        "question",
        [
            "apa isi dokumen tiketing?",
            "berapa hari SLA penyelesaian permintaan?",
            "jelaskan prosedur pengajuan tiket",
            "siapa presiden pertama indonesia?",
            "bagaimana cara mengajukan cuti?",
        ],
    )
    def test_pertanyaan_isi_tidak_terdeteksi(self, question: str) -> None:
        # Pertanyaan isi harus tetap lewat retrieval. Salah mendeteksi di sini
        # berarti pertanyaan yang jawabannya ada di dokumen justru dijawab
        # dari daftar berkas.
        assert is_collection_question(question) is False

    def test_pertanyaan_kosong(self) -> None:
        assert is_collection_question("") is False
        assert is_collection_question("   ") is False


class TestPencocokanTopik:
    def test_bentuk_berimbuhan_menemukan_katanya(self) -> None:
        # "tiketing" harus menemukan "panduan-tiket-layanan.md". Tanpa
        # pencocokan awalan, dokumen yang jelas relevan dilaporkan tidak ada.
        terms = topic_terms("carikan dokumen terkait dengan tiketing")
        assert matches_topic("panduan-tiket-layanan.md", terms) is True

    def test_awalan_kata_cocok(self) -> None:
        terms = topic_terms("carikan dokumen tentang cuti")
        assert matches_topic("kebijakan-cuti.txt", terms) is True

    def test_dokumen_tidak_relevan_tidak_cocok(self) -> None:
        terms = topic_terms("carikan dokumen terkait tiketing")
        assert matches_topic("laporan-infrastruktur.pdf", terms) is False

    def test_stopword_dibuang(self) -> None:
        terms = topic_terms("carikan dokumen terkait dengan tiketing")
        # Kata umum tidak boleh ikut jadi kata kunci, karena akan mencocokkan
        # hampir semua berkas.
        assert "dokumen" not in terms
        assert "carikan" not in terms
        assert "terkait" not in terms
        assert "tiketing" in terms

    def test_kata_pendek_dibandingkan_apa_adanya(self) -> None:
        # Kata tiga huruf tidak dipotong jadi awalan, supaya tidak
        # mencocokkan terlalu banyak berkas.
        assert matches_topic("sop.md", ["sop"]) is True
        assert matches_topic("laporan.md", ["sop"]) is False
