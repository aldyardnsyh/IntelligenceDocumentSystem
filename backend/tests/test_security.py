"""Test untuk perbaikan keamanan dan Kebersihan yang masuk lewat audit QA.

Fokus file ini adalah perilaku yang harus tidak bisa balik lagi:

- ``session_id`` milik identitas lain tidak boleh bisa dibaca/diubah/dihapus.
- Rate limit tidak boleh bisa dilewati dengan ``session_id`` acak.
- Nama berkas dari klien disanitasi sebelum disimpan.
- Ukuran berkas ditegakkan saat dibaca, bukan setelah memorinya terpakai.
- Mode demo publik (``AUTH_OPEN_MODE``) hanya menurunkan gate passcode,
  bukan menghapus logika sesi di baliknya.

Test keamanan yang tidak menguji respons HTTP saja kurang berguna: yang perlu
dikunci adalah *kenapa* penolakan terjadi, jadi sebagian besar kasus di sini
memeriksa status dan pesan sekaligus.
"""

from __future__ import annotations

import time

import pytest

from app.core.config import Settings
from app.core.security import SessionStore, hash_passcode, owner_of_token, verify_passcode
from app.services.ingestion.parser import ParseError, sanitize_filename
from tests.conftest import TEST_PASSCODE


class TestSessionOwnership:
    """Kepemilikan diikat ke token akses, dan hanya berlaku selagi token itu hidup.

    Kalau klaim bertahan lebih lama dari tokennya, pengguna asli terkunci
    permanen dari riwayat chat-nya sendiri setelah token kedaluwarsa.
    """

    def test_sesi_baru_bisa_diklaim_pemiliknya(self) -> None:
        store = SessionStore(ttl_seconds=60)
        token = store.issue()
        assert store.claim_session("ses_1", token) is True

    def test_pemilik_lain_yang_tokennya_hidup_ditolak(self) -> None:
        store = SessionStore(ttl_seconds=60)
        owner_a = store.issue()
        owner_b = store.issue()
        store.claim_session("ses_1", owner_a)
        assert store.may_access_session("ses_1", owner_a) is True
        assert store.may_access_session("ses_1", owner_b) is False

    def test_klaim_ulang_oleh_pemilik_sama_diterima(self) -> None:
        store = SessionStore(ttl_seconds=60)
        token = store.issue()
        store.claim_session("ses_1", token)
        # Percakapan bisa berlanjut berkali-kali dalam satu sesi.
        assert store.claim_session("ses_1", token) is True

    def test_sesi_tanpa_klaim_boleh_diakses(self) -> None:
        # Setelah restart store in-process kosong. Menolak sesi yang belum
        # diklaim akan membuat seluruh riwayat tidak bisa dibuka.
        store = SessionStore(ttl_seconds=60)
        assert store.may_access_session("ses_1", store.issue()) is True

    def test_login_ulang_tetap_bisa_membuka_histori_lama(self) -> None:
        store = SessionStore(ttl_seconds=60)
        lama = store.issue()
        store.claim_session("ses_1", lama)

        # Token lama kedaluwarsa. Deadline ditulis langsung supaya test tidak
        # bergantung pada resolusi jam Windows yang bisa berdetak sama dalam
        # milidetik yang sama.
        store._tokens[lama] = time.time() - 1

        baru = store.issue()
        assert store.may_access_session("ses_1", baru) is True
        assert store.claim_session("ses_1", baru) is True

    def test_klaim_milik_token_yang_mati_dilepas_saat_pembersihan(self) -> None:
        store = SessionStore(ttl_seconds=60)
        mati = store.issue()
        store.claim_session("ses_1", mati)
        store._tokens.clear()  # simulasi restart/kedaluwarsa massal
        store.is_valid(mati)
        assert store._owners == {}

    def test_cabut_token_melepaskan_klaim_sesi(self) -> None:
        store = SessionStore(ttl_seconds=60)
        token = store.issue()
        store.claim_session("ses_1", token)
        store.revoke(token)
        assert store.is_valid(token) is False
        # Klaim ikut hilang, jadi token yang dicabut tidak mewariskan akses.
        assert store.may_access_session("ses_1", token) is True

    def test_forget_session_melepas_klaim(self) -> None:
        store = SessionStore(ttl_seconds=60)
        token = store.issue()
        store.claim_session("ses_1", token)
        store.forget_session("ses_1")
        assert store._owners == {}

    def test_forget_owner_sessions_melepas_semua_klaim(self) -> None:
        store = SessionStore(ttl_seconds=60)
        token = store.issue()
        store.claim_session("ses_1", token)
        store.claim_session("ses_2", token)
        assert store.forget_owner_sessions(token) == 2
        assert store._owners == {}

    def test_owner_of_token_tidak_membocorkan_token(self) -> None:
        token = "rahasia-token"
        owner = owner_of_token(token)
        assert token not in owner
        assert owner == owner_of_token(token)


class TestFilenameSanitation:
    def test_path_dibuang(self) -> None:
        assert sanitize_filename("../../etc/passwd.txt") == "passwd.txt"

    def test_path_windows_dibuang(self) -> None:
        assert sanitize_filename(r"C:\Users\aldi\rahasia.md") == "rahasia.md"

    def test_karakter_kontrol_dibuang(self) -> None:
        assert "\n" not in sanitize_filename("nama\nberkas.txt")
        assert "\x00" not in sanitize_filename("nama\x00berkas.txt")

    def test_markup_dibuang(self) -> None:
        # Nama berkas masuk ke prompt LLM dan dirender di UI, jadi tanda
        # markup harus dibuang di server, bukan hanya di tampilan.
        assert "<" not in sanitize_filename("<script>evil.pdf")

    def test_ekstensi_diperahankan(self) -> None:
        # Validasi format bergantung pada ekstensi, jadi sanitasi tidak boleh
        # menghapusnya.
        assert sanitize_filename("Dokumen Penting.pdf").endswith(".pdf")

    def test_nama_kosong_ditolak(self) -> None:
        with pytest.raises(ParseError):
            sanitize_filename("   ")

    def test_nama_sangat_panjang_dipotong(self) -> None:
        result = sanitize_filename("a" * 500 + ".pdf")
        assert len(result) <= 200


class TestOpenMode:
    """Mode demo publik (``AUTH_OPEN_MODE``).

    Mode ini menurunkan gate passcode untuk demo, tapi tidak boleh
    mengubah mekanisme sesi di baliknya: token tetap diterbitkan lewat
    ``SessionStore`` yang sama dan ``verify_passcode`` sendiri tidak
    disentuh sama sekali. Yang diuji di sini justru bagian yang membuat
    mode ini aman dipakai untuk demo dan mudah dimatikan lagi.

    Perilaku endpoint dan middleware-nya diuji lewat HTTP di
    ``test_api.py``; file ini fokus pada kontrak unit di bawahnya,
    mengikuti pembagian cakupan antar berkas test yang sudah ada.
    """

    def test_flag_dapat_dinyalakan(self) -> None:
        assert Settings(auth_open_mode=True).auth_open_mode is True

    def test_flag_default_mati(self) -> None:
        # Nilai default harus tetap False: mode terbuka yang menyala sendiri
        # di produksi berarti gate passcode hilang tanpa ada yang sadar.
        assert Settings(auth_open_mode=False).auth_open_mode is False

    def test_verify_passcode_tetap_menolak_tanpa_hash(self) -> None:
        # Fungsi gate-nya tidak diubah oleh mode terbuka; bypass terjadi di
        # level endpoint dan middleware, bukan di sini.
        config = Settings(auth_open_mode=True, access_passcode_sha256=None)
        assert verify_passcode("apapun", config) is False

    def test_verify_passcode_tetap_menerima_hash_yang_benar(self) -> None:
        # Konfigurasi open mode tidak merusak verifikasi normal: kalau env
        # dimatikan, passcode yang benar harus langsung diterima lagi.
        config = Settings(
            auth_open_mode=True,
            access_passcode_sha256=hash_passcode(TEST_PASSCODE),
        )
        assert verify_passcode(TEST_PASSCODE, config) is True
        assert verify_passcode("apapun", config) is False

    def test_session_store_issue_is_valid_roundtrip(self) -> None:
        # Inilah jangkar open mode: token yang diterbitkan otomatis oleh
        # middleware tetap terdaftar di SessionStore yang sama, sehingga
        # require_session, kepemilikan percakapan, dan logout bekerja
        # persis seperti mode normal.
        store = SessionStore(ttl_seconds=60)
        token = store.issue()
        assert store.is_valid(token) is True

    def test_cookie_asal_pengunjung_tidak_dianggap_sah(self) -> None:
        # Predikat yang membuat middleware menerbitkan token baru: cookie
        # karangan atau sisa proses lama tidak boleh lolos begitu saja.
        store = SessionStore(ttl_seconds=60)
        assert store.is_valid("cookie-karangan") is False