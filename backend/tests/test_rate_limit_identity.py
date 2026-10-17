"""Test bahwa kuota rate limit tidak bisa direset dengan login ulang.

Bug yang dikunci di sini: kunci bucket rate limit dulu memakai token sesi.
Token berubah setiap kali pengguna login lagi, jadi bucket ikut baru. Artinya
pengguna bisa memakai kuota Groq tanpa batas hanya dengan logout lalu masuk
lagi, tanpa menunggu jendela waktu habis.
"""

from __future__ import annotations

import pytest

from app.core.config import Settings
from app.core.security import hash_passcode


class TestIdentitasRateLimit:
    """Identitas rate limit harus stabil, bukan token yang berganti."""

    def test_hash_passcode_dipakai_sebagai_identitas(self) -> None:
        digest = hash_passcode("rahasia-uji")
        settings = Settings(access_passcode_sha256=digest)
        assert settings.rate_limit_identity() == digest

    def test_stabil_lintas_pemanggilan(self) -> None:
        """Dipanggil berkali-kali, hasilnya sama."""
        digest = hash_passcode("rahasia-uji")
        settings = Settings(access_passcode_sha256=digest)
        hasil = {settings.rate_limit_identity() for _ in range(5)}
        assert len(hasil) == 1

    def test_dua_instans_dengan_passcode_sama_berbagi_identitas(self) -> None:
        """Dua proses dengan passcode sama menghasilkan kunci yang sama.

        Ini yang membuat batas tetap berlaku setelah backend dijalankan
        ulang, walaupun semua token lama sudah tidak sah.
        """
        digest = hash_passcode("rahasia-uji")
        a = Settings(access_passcode_sha256=digest)
        b = Settings(access_passcode_sha256=digest)
        assert a.rate_limit_identity() == b.rate_limit_identity()

    def test_passcode_berbeda_menghasilkan_identitas_berbeda(self) -> None:
        a = Settings(access_passcode_sha256=hash_passcode("satu"))
        b = Settings(access_passcode_sha256=hash_passcode("dua"))
        assert a.rate_limit_identity() != b.rate_limit_identity()

    def test_tanpa_passcode_tetap_deterministik(self) -> None:
        """Nilai cadangan tidak boleh acak.

        Tanpa passcode, tidak ada sesi yang bisa terbit, jadi kasus ini tidak
        pernah terjadi pada request nyata. Tapi fungsinya harus tetap
        deterministik supaya tidak memicu bug aneh kalau dipanggil dari test.
        """
        settings = Settings(access_passcode_sha256=None)
        assert settings.rate_limit_identity() == "tanpa-passcode"
        assert settings.rate_limit_identity() == settings.rate_limit_identity()

    def test_identitas_bukan_passcode_mentah(self) -> None:
        """Yang dipakai hash, bukan passcode aslinya.

        Kunci ini bisa ikut tercatat di log atau di memory store. Kalau
        isinya passcode asli, itu kebocoran.
        """
        settings = Settings(access_passcode_sha256=hash_passcode("passcode-asli"))
        identitas = settings.rate_limit_identity()
        assert "passcode-asli" not in identitas
        assert len(identitas) == 64


class TestKuotaBertahanSetelahLoginUlang:
    """Simulasi perilaku: login ulang tidak membuka kuota baru."""

    def test_token_baru_identitas_rate_limit_tetap(self) -> None:
        """Token berbeda, identitas rate limit sama.

        Ini inti perbaikannya. ``require_session`` menaruh token di
        ``auth_owner`` dan identitas stabil di ``rate_key``. Token boleh
        berganti, tapi ``rate_key`` tidak.
        """
        from app.core.security import SessionStore

        store = SessionStore(ttl_seconds=3600)
        settings = Settings(access_passcode_sha256=hash_passcode("rahasia-uji"))

        token_lama = store.issue()
        token_baru = store.issue()
        assert token_lama != token_baru, "token harus berbeda setelah login ulang"

        # Identitas rate limit tidak bergantung pada token sama sekali.
        kunci = settings.rate_limit_identity()
        assert kunci == settings.rate_limit_identity()
        assert token_lama not in kunci
        assert token_baru not in kunci

    @pytest.mark.parametrize("passcode", ["satu-panjang", "dua-panjang", "tiga-panjang"])
    def test_hash_selalu_64_karakter(self, passcode: str) -> None:
        settings = Settings(access_passcode_sha256=hash_passcode(passcode))
        assert len(settings.rate_limit_identity()) == 64
