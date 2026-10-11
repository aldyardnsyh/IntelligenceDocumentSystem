"""Utilitas keamanan: verifikasi passcode access gate.

Passcode tidak pernah dibandingkan sebagai plaintext. Yang disimpan di
environment variable adalah SHA-256-nya, sehingga bocornya isi environment tidak
langsung berarti bypass.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from dataclasses import dataclass, field

from app.core.config import Settings

SESSION_COOKIE_NAME = "ida_session"


def hash_passcode(passcode: str) -> str:
    """SHA-256 hex dari passcode."""
    return hashlib.sha256(passcode.encode("utf-8")).hexdigest()


def verify_passcode(candidate: str, settings: Settings) -> bool:
    """Bandingkan passcode dengan hash yang tersimpan, dalam waktu konstan.

    ``hmac.compare_digest`` dipakai supaya selisih waktu tidak membocorkan
    berapa banyak karakter yang sudah cocok.
    """
    if not settings.access_passcode_sha256:
        # Tidak dikonfigurasi: gerbang menolak semua, bukan menerima semua.
        # Mode ini hanya boleh terjadi kalau operator lupa mengisinya.
        return False
    if not candidate:
        return False
    return hmac.compare_digest(
        hash_passcode(candidate), settings.access_passcode_sha256.lower()
    )


def make_session_token() -> str:
    """Token sesi acak.

    Token ini adalah kredensial, bukan sekadar pengenal. Yang membuatnya
    aman adalah ``SessionStore`` yang mencatat token mana yang sudah
    dicabut atau kedaluwarsa, jadi token palsu langsung ditolak.
    """
    return secrets.token_urlsafe(32)


@dataclass(slots=True)
class SessionStore:
    """Daftar token sesi yang masih sah, dengan masa berlaku.

    Menyimpan token di memori, bukan hanya memercayai cookie, penting karena
    kalau tidak, siapa pun yang memasang cookie dengan string acak apa pun akan
    lolos. Daftar ini juga yang membuat ``/auth/logout`` benar-benar mencabut
    akses: menghapus cookie tanpa menghapus token dari daftar hanya menjatuhkan
    klien, bukan mencabut akses.

    Store ini juga menyimpan mapping ``session_id`` (percakapan) -> ``owner``
    (hash token akses). Tanpa itu, siapa pun yang punya cookie sah bisa
    membaca, mengganti nama, dan menghapus percakapan milik orang lain,
    karena ``session_id`` hanya berupa tebakan yang dikirim klien.

    Trade-off yang perlu diketahui: store ini in-process, jadi token hilang
    saat restart. Untuk portofolio satu-pengguna itu dapat diterima, dan
    dampaknya hanya "harus masuk lagi", bukan celah keamanan. Untuk banyak
    instance, pindahkan ke Redis.
    """

    ttl_seconds: int
    _tokens: dict[str, float] = field(default_factory=dict)
    # ``session_id`` -> token yang mengklaimnya.
    #
    # Yang disimpan token, bukan hash-nya, justru karena gunanya: pertanyaan
    # "apakah klaim ini masih hidup?" harus bisa dijawab. Kalau yang disimpan
    # hash, store tidak tahu apakah token aslinya masih hidup,
    # dan setelah token lama kedaluwarsa, pengguna asli terkunci permanen dari
    # riwayat chat-nya sendiri dengan 403 yang tidak punya jalan keluar.
    _owners: dict[str, str] = field(default_factory=dict)

    def issue(self) -> str:
        token = make_session_token()
        self._tokens[token] = time.time() + self.ttl_seconds
        return token

    def is_valid(self, token: str) -> bool:
        now = time.time()
        # Bersihkan yang kedaluwarsa sambil memeriksa, supaya dict tidak
        # tumbuh tanpa batas.
        expired = [key for key, deadline in self._tokens.items() if deadline < now]
        for key in expired:
            self._tokens.pop(key, None)
        # Klaim milik token yang sudah mati ikut dilepas, bukan hanya tokennya.
        for session_id, owner in list(self._owners.items()):
            if not self._is_alive(owner):
                self._owners.pop(session_id, None)
        return token in self._tokens

    def revoke(self, token: str) -> None:
        self._tokens.pop(token, None)
        # Sesi percakapan milik pemilik token ini ikut dilepas, supaya token
        # lama yang bocor tidak masih bisa mengubah state percakapan.
        for session_id, owner in list(self._owners.items()):
            if owner == token:
                self._owners.pop(session_id, None)

    def clear(self) -> None:
        self._tokens.clear()
        self._owners.clear()

    # ------------------------------------------------------- kepemilikan sesi

    def claim_session(self, session_id: str, owner: str) -> bool:
        """Miliki ``session_id``; True kalau berhasil.

        Sesi yang belum punya pemilik diklaim oleh pemanggil pertama. Klaim
        milik token yang sudah tidak berlaku dianggap bebas, itulah yang
        membuat login ulang (token baru) tetap bisa membuka riwayat lama.
        """
        current = self._owners.get(session_id)
        if current is None or current == owner or not self._is_alive(current):
            self._owners[session_id] = owner
            return True
        return False

    def may_access_session(self, session_id: str, owner: str) -> bool:
        """True kalau pemanggil boleh menyentuh sesi ini.

        Sesi tanpa klaim dianggap bebas: metadata sesi tidak punya kolom
        pemilik, jadi setelah restart store ini kosong dan pencatatan klaim
        hilang. Menolak di titik itu akan membuat seluruh riwayat pengguna
        tidak bisa dibuka hanya karena server restart.
        """
        current = self._owners.get(session_id)
        if current is None or current == owner:
            return True
        # Klaim yang ditinggalkan token yang sudah mati tidak menghalangi.
        return not self._is_alive(current)

    def _is_alive(self, token: str) -> bool:
        """True kalau token masih ada dan belum kedaluwarsa.

        Deadline dibaca, bukan hanya keberadaan key: pada Windows resolusi
        `time.time()` bisa sedetik sehingga token dengan TTL 0 masih terlihat
        "ada" walau sudah lewat.
        """
        deadline = self._tokens.get(token)
        return deadline is not None and deadline >= time.time()

    def forget_session(self, session_id: str) -> None:
        self._owners.pop(session_id, None)

    def forget_owner_sessions(self, owner: str) -> int:
        """Lepas semua klaim milik satu token. Dipakai reset semua sesi."""
        stale = [sid for sid, token in self._owners.items() if token == owner]
        for session_id in stale:
            self._owners.pop(session_id, None)
        return len(stale)

    def __len__(self) -> int:
        return len(self._tokens)


def owner_of_token(token: str) -> str:
    """Identitas pemilik sesi dalam bentuk yang tidak bisa dipalsukan.

    Dipakai untuk kunci rate limit (log harus bisa dibaca tanpa membocorkan
    token). Untuk kepemilikan sesi dipakai token-nya langsung, karena store
    perlu tahu apakah klaim itu masih hidup, lihat ``SessionStore``.
    """
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


@dataclass
class SlidingWindowLimiter:
    """Rate limit sliding window in-process.

    Cukup untuk satu instance. Untuk banyak instance, limiter ini harus
    pindah ke Redis; lihat ``app.services.memory.rate_limit`` untuk versi
    terdistribusi.
    """

    max_attempts: int
    window_seconds: int
    _hits: dict[str, list[float]] = field(default_factory=dict)

    def _prune(self, key: str, now: float) -> list[float]:
        recent = [ts for ts in self._hits.get(key, []) if now - ts < self.window_seconds]
        if recent:
            self._hits[key] = recent
        else:
            self._hits.pop(key, None)
        return recent

    def is_blocked(self, key: str) -> bool:
        """True kalau sudah ``max_attempts`` percobaan dalam jendela."""
        now = time.time()
        return len(self._prune(key, now)) >= self.max_attempts

    def retry_after(self, key: str) -> int:
        """Detik sampai jendela bergeser, minimal 1."""
        now = time.time()
        recent = self._prune(key, now)
        if not recent:
            return 0
        return max(1, int(self.window_seconds - (now - recent[0])) + 1)

    def record(self, key: str) -> None:
        """Catat satu percobaan gagal."""
        now = time.time()
        self._hits.setdefault(key, []).append(now)

    def clear(self, key: str) -> None:
        self._hits.pop(key, None)
