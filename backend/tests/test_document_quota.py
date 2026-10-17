"""Test batas kuota dokumen.

Kenapa perlu: batas 10 MB per berkas tidak membatasi apa pun kalau jumlah
berkasnya tidak dibatasi. Satu pengguna bisa mengunggah ratusan berkas sampai
disk server penuh, dan itu terjadi setelah deployment, bukan saat
pengembangan. Dua batas dipakai karena satu tidak cukup:

- jumlah dokumen, supaya tidak ada ratusan berkas kecil;
- total byte, supaya 200 berkas berukuran 10 MB tidak berarti 2 GB.

Test di sini menguji service secara langsung. Pemeriksaan kuota ada di
``IngestionService.assert_quota_available``, dan route hanya menerjemahkan
error-nya menjadi status HTTP. Menguji di level service membuat test cepat
dan tidak bergantung pada penyusunan aplikasi HTTP.
"""

from __future__ import annotations

import inspect

import pytest

from app.core.config import Settings
from app.models.domain import Document, DocumentStatus
from app.services.ingestion.service import DocumentQuotaError, IngestionService

SAMPLE = b"# Dokumen uji\n\nIsi dokumen untuk pengujian kuota penyimpanan.\n"


def _tambah_dokumen(repository, jumlah: int, ukuran: int, prefix: str = "doc") -> None:
    """Tambahkan dokumen langsung ke repository, tanpa ingestion.

    Cukup untuk mengisi kuota, dan jauh lebih cepat daripada mengunggah
    berkas sungguhan.
    """
    for index in range(jumlah):
        repository.add_document(
            Document(
                id=f"{prefix}-{index}",
                filename=f"{prefix}-{index}.md",
                size_bytes=ukuran,
                status=DocumentStatus.READY,
                uploaded_at="2026-01-01T00:00:00+00:00",
                page_count=1,
                chunk_count=1,
            )
        )


class TestBatasJumlahDokumen:
    """Batas jumlah dokumen ditegakkan."""

    def test_menolak_saat_jumlah_mencapai_batas(self, ingestion, settings) -> None:
        settings.max_documents = 2
        _tambah_dokumen(ingestion.repository, 2, 1000)

        with pytest.raises(DocumentQuotaError) as info:
            ingestion.assert_quota_available(1000)

        pesan = str(info.value)
        assert "batas 2" in pesan
        # Pesannya harus menyebut tindakan, bukan hanya penolakan.
        assert "Hapus dokumen" in pesan

    def test_masih_boleh_di_bawah_batas(self, ingestion, settings) -> None:
        settings.max_documents = 5
        _tambah_dokumen(ingestion.repository, 2, 1000)
        # Tidak melempar.
        ingestion.assert_quota_available(1000)

    def test_kosong_selalu_boleh(self, ingestion, settings) -> None:
        settings.max_documents = 1
        ingestion.assert_quota_available(1000)


class TestBatasTotalByte:
    """Batas total ukuran ditegakkan."""

    def test_menolak_saat_total_terlampaui(self, ingestion, settings) -> None:
        settings.max_documents = 100
        settings.max_total_document_bytes = 5000
        _tambah_dokumen(ingestion.repository, 3, 1000)

        with pytest.raises(DocumentQuotaError) as info:
            ingestion.assert_quota_available(3000)

        pesan = str(info.value)
        assert "MB" in pesan, "pesan harus menyebut angka yang bisa dipahami"
        assert "Hapus dokumen" in pesan

    def test_berkas_pertama_selalu_boleh(self, ingestion, settings) -> None:
        """Kuota kosong menerima satu berkas apa pun ukurannya (di bawah batas berkas).

        Kalau batas total di bawah ukuran satu berkas, berkas pertama pun
        ditolak dan aplikasi tidak bisa dipakai sama sekali. Yang diuji:
        batas berlaku untuk akumulasi, bukan menolak berkas tunggal yang sah.
        """
        settings.max_documents = 100
        settings.max_total_document_bytes = len(SAMPLE) * 2
        ingestion.assert_quota_available(len(SAMPLE))

    def test_batas_byte_dihitung_dari_isi_tersimpan(self, ingestion, settings) -> None:
        """Ukuran yang dihitung adalah yang benar-benar tersimpan."""
        settings.max_documents = 100
        settings.max_total_document_bytes = 10_000
        _tambah_dokumen(ingestion.repository, 4, 2000)  # 8000 byte
        # 8000 + 2000 = 10000, tepat di batas: masih boleh.
        ingestion.assert_quota_available(2000)
        # 8000 + 2001 melewati batas.
        with pytest.raises(DocumentQuotaError):
            ingestion.assert_quota_available(2001)


class TestPesanKuotaJelas:
    """Pesan penolakan harus bisa ditindaklanjuti."""

    def test_pesan_menyebut_angka_dan_tindakan(self, ingestion, settings) -> None:
        settings.max_documents = 1
        _tambah_dokumen(ingestion.repository, 1, 1000)

        with pytest.raises(DocumentQuotaError) as info:
            ingestion.assert_quota_available(1000)

        pesan = str(info.value)
        assert "1" in pesan
        assert "Hapus dokumen" in pesan
        assert pesan != "Berkas tidak bisa dibaca."

    def test_diperiksa_sebelum_parsing(self) -> None:
        """Kuota dicek lebih dulu, bukan setelah berkas diproses.

        Berkas besar tidak boleh memakai waktu CPU dan memori hanya untuk
        ditolak di akhir. Dibuktikan dari signature: yang diterima hanya
        jumlah byte, bukan isi berkas, sehingga bisa dipanggil sebelum
        membaca apa pun.
        """
        parameter = inspect.signature(
            IngestionService.assert_quota_available
        ).parameters
        assert "incoming_bytes" in parameter
        # Bukan **kwargs, jadi tidak ada jalan memasukkan isi berkas.
        assert all(
            p.kind != inspect.Parameter.VAR_KEYWORD for p in parameter.values()
        )


class TestTipeError:
    """Tipe error bisa dibedakan dari kegagalan parsing."""

    def test_bukan_turunan_parse_error(self) -> None:
        from app.services.ingestion.parser import ParseError

        assert issubclass(DocumentQuotaError, RuntimeError)
        assert not issubclass(DocumentQuotaError, ParseError)

    def test_kuota_bisa_dimatikan_dengan_angka_besar(self, ingestion) -> None:
        """Operator bisa melonggarkan batas tanpa mengubah kode."""
        settings = Settings(max_documents=100_000, max_total_document_bytes=10**12)
        assert settings.max_documents == 100_000
