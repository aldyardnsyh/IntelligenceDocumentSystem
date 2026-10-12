"""Test konfigurasi yang berbahaya saat aplikasi di-host.

Semua setelan di sini adalah yang "supaya cepat jalan" di mesin sendiri, tapi
berubah jadi lubang begitu ada di internet. Test ini mengunci janji bahwa
konfigurasi seperti itu tidak bisa lolos diam-diam.

Bedanya dengan test lain: yang diuji bukan perilaku request, melainkan
validasi konfigurasi dan apa yang dibocorkan endpoint publik.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.core.security import hash_passcode


class TestCorsTidakBolehWildcard:
    """CORS `*` ditolak, bukan hanya diperingatkan.

    Aplikasi ini memakai cookie sesi. Starlette dengan
    ``allow_credentials=True`` memantulkan origin pemanggil apa adanya begitu
    request membawa cookie, jadi dengan ``*`` situs mana pun bisa membaca
    respons API ini memakai sesi pengguna yang sedang login. Perilaku itu
    sudah dibuktikan dengan menjalankan aplikasinya, bukan dari teori.
    """

    def test_wildcard_ditolak(self) -> None:
        with pytest.raises(ValidationError, match="tidak boleh berisi"):
            Settings(cors_origins=["*"])

    def test_wildcard_di_tengah_daftar_juga_ditolak(self) -> None:
        with pytest.raises(ValidationError, match="tidak boleh berisi"):
            Settings(cors_origins=["https://a.example", "*"])

    def test_origin_spesifik_diterima(self) -> None:
        settings = Settings(cors_origins=["https://a.example", "http://localhost:3000"])
        assert settings.cors_origins == ["https://a.example", "http://localhost:3000"]

    def test_dari_env_string_dipisah_koma(self) -> None:
        settings = Settings(cors_origins="https://a.example,https://b.example")
        assert settings.cors_origins == ["https://a.example", "https://b.example"]


class TestPasscodeHashDivalidasi:
    """Yang diisi harus hash SHA-256, bukan passcode mentah.

    Kesalahan yang paling mudah terjadi: operator mengisi passcode aslinya.
    Gejalanya "login selalu gagal" tanpa pesan yang menjelaskan, dan
    penyebabnya sulit terlihat karena nilainya tampak seperti string biasa.
    """

    def test_passcode_mentah_ditolak(self) -> None:
        with pytest.raises(ValidationError, match="64 karakter heksadesimal"):
            Settings(access_passcode_sha256="passcode-saya")

    def test_hash_terlalu_pendek_ditolak(self) -> None:
        with pytest.raises(ValidationError, match="64 karakter heksadesimal"):
            Settings(access_passcode_sha256="a" * 63)

    def test_hash_dengan_karakter_bukan_hex_ditolak(self) -> None:
        with pytest.raises(ValidationError, match="64 karakter heksadesimal"):
            Settings(access_passcode_sha256="z" * 64)

    def test_hash_benar_diterima(self) -> None:
        digest = hash_passcode("rahasia-uji")
        settings = Settings(access_passcode_sha256=digest)
        assert settings.access_passcode_sha256 == digest

    def test_hash_huruf_besar_dinormalkan(self) -> None:
        digest = hash_passcode("rahasia-uji").upper()
        settings = Settings(access_passcode_sha256=digest)
        assert settings.access_passcode_sha256 == digest.lower()

    def test_kosong_berarti_none(self) -> None:
        # Kosong bukan error: aplikasi tetap start, dan semua login ditolak
        # sampai operator mengisinya. Itu perilaku yang benar untuk
        # deployment yang belum selesai dikonfigurasi.
        settings = Settings(access_passcode_sha256="")
        assert settings.access_passcode_sha256 is None


class TestDokumentasiApiDefault:
    """Dokumentasi API mati secara default."""

    def test_default_mati(self) -> None:
        assert Settings().api_docs_enabled is False

    def test_bisa_dinyalakan(self) -> None:
        assert Settings(api_docs_enabled=True).api_docs_enabled is True
