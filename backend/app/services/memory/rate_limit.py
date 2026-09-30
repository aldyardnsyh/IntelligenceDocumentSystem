"""Rate limit terdistribusi via memory store.

Rate limit per sesi dibutuhkan untuk melindungi kuota free tier. Batas per IP
saja tidak cukup: satu orang bisa membuka banyak sesi, atau satu sesi dipakai
beberapa orang sekaligus. Batas per sesi menutup kedua kasus itu.
"""

from __future__ import annotations

import time

from app.core.config import Settings
from app.services.memory.store import CACHE_PREFIX, MemoryStore

LIMIT_PREFIX = "ratelimit:"


class RateLimiter:
    """Sliding window counter yang disimpan di memory store.

    Berbeda dengan limiter in-process di ``core.security``, yang ini terbagi
    antar instance, karena state-nya ada di Redis.
    """

    def __init__(self, store: MemoryStore, settings: Settings) -> None:
        self._store = store
        self._max = settings.query_max_per_session
        self._window = settings.query_window_seconds

    def _key(self, bucket: str) -> str:
        """Kunci lengkap di memory store.

        Counter ini sengaja disimpan lewat API cache, jadi ``CACHE_PREFIX``
        harus ikut. Versi sebelumnya melepaskannya, sehingga ``reset`` dan
        ``delete_by_prefix`` tidak pernah mencocokkan apa pun: penghitung
        tidak pernah benar-benar dihapus, dan sesi yang sudah direset masih
        terbaca sebagai habis kuota.
        """
        return f"{LIMIT_PREFIX}{bucket}"

    async def check(self, bucket: str) -> tuple[bool, int]:
        """Periksa dan catat satu pemakaian.

        Returns:
            ``(boleh, retry_after_detik)``. Kalau ``boleh`` False,
            ``retry_after`` memberi tahu berapa lama harus menunggu.
        """
        key = self._key(bucket)
        now = time.time()

        raw = await self._store.get_cached(key)
        timestamps: list[float] = []
        if isinstance(raw, dict):
            stored = raw.get("hits")
            if isinstance(stored, list):
                timestamps = [float(item) for item in stored if isinstance(item, int | float)]

        recent = [stamp for stamp in timestamps if now - stamp < self._window]

        if len(recent) >= self._max:
            retry_after = max(1, int(self._window - (now - recent[0])) + 1)
            return False, retry_after

        recent.append(now)
        # TTL diset ke jendela penuh plus sedikit, supaya counter yang sudah
        # kedaluwarsa tidak menumpuk di memory store.
        await self._store.set_cached(
            key, {"hits": recent}, self._window + 5
        )
        return True, 0

    async def reset(self, bucket: str) -> None:
        await self._store.delete_by_prefix(f"{CACHE_PREFIX}{self._key(bucket)}")
