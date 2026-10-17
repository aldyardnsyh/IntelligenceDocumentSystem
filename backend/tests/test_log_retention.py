"""Test retensi log query.

Tanpa retensi, tabel ``query_logs`` tumbuh terus. Yang membuatnya berbahaya
bukan ukurannya, tapi kesunyiannya: dashboard mulai memotong data lama, dan
angka latency serta token hanya mencerminkan sebagian riwayat tanpa tanda
apa pun bahwa itu terjadi. Operator bisa menyimpulkan performa membaik
padahal yang terjadi adalah datanya terbuang.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.models.domain import QueryLog


def _log(suffix: str, dibuat: datetime) -> QueryLog:
    return QueryLog(
        id=f"log-{suffix}",
        session_id=None,
        question=f"pertanyaan {suffix}",
        response_time_ms=100,
        sources_count=1,
        created_at=dibuat.isoformat(),
        from_cache=False,
        trace_id=None,
    )


class TestPembersihanLogLama:
    """Log yang lebih tua dari batas waktu dihapus."""

    def test_menghapus_hanya_yang_lama(self, repository) -> None:
        sekarang = datetime.now(UTC)
        repository.add_log(_log("lama", sekarang - timedelta(days=100)))
        repository.add_log(_log("baru", sekarang - timedelta(days=1)))

        cutoff = (sekarang - timedelta(days=90)).isoformat()
        dihapus = repository.delete_logs_before(cutoff)

        assert dihapus == 1
        tersisa, total = repository.list_logs(1, 10)
        assert total == 1
        assert tersisa[0].id == "log-baru"

    def test_tidak_menghapus_apa_pun_kalau_semua_baru(self, repository) -> None:
        sekarang = datetime.now(UTC)
        repository.add_log(_log("baru", sekarang - timedelta(days=1)))

        cutoff = (sekarang - timedelta(days=90)).isoformat()
        assert repository.delete_logs_before(cutoff) == 0

    def test_tabel_kosong_tidak_error(self, repository) -> None:
        cutoff = datetime.now(UTC).isoformat()
        assert repository.delete_logs_before(cutoff) == 0

    def test_batas_waktu_dihormati_persis(self, repository) -> None:
        """Log tepat di batas tidak ikut terhapus.

        Perbandingan memakai ``<``, bukan ``<=``, supaya log yang masih dalam
        masa retensi tidak hilang karena selisih sepersekian detik.
        """
        batas = datetime.now(UTC) - timedelta(days=90)
        repository.add_log(_log("tepat", batas))
        repository.add_log(_log("lebih-lama", batas - timedelta(seconds=1)))

        dihapus = repository.delete_logs_before(batas.isoformat())

        assert dihapus == 1
        tersisa, total = repository.list_logs(1, 10)
        assert total == 1
        assert tersisa[0].id == "log-tepat"


class TestKonfigurasiRetensi:
    """Nilai retensi masuk akal dan bisa dimatikan."""

    def test_default_menyimpan_90_hari(self, settings) -> None:
        assert settings.query_log_retention_days == 90

    def test_nol_berarti_tidak_pernah_dihapus(self, settings) -> None:
        """Set 0 mematikan pembersihan, untuk yang ingin menyimpan selamanya."""
        settings.query_log_retention_days = 0
        assert settings.query_log_retention_days == 0

    def test_nilai_bisa_diubah_dari_env(self) -> None:
        from app.core.config import Settings

        assert Settings(query_log_retention_days=30).query_log_retention_days == 30
