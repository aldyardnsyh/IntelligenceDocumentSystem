"""Rate limit terdistribusi via memory store.

Rate limit per sesi dibutuhkan untuk melindungi kuota free tier. Batas per IP
saja tidak cukup: satu orang bisa membuka banyak sesi, atau satu sesi dipakai
beberapa orang sekaligus. Batas per sesi menutup kedua kasus itu.
"""

from __future__ import annotations

import asyncio
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
        # Lock per bucket. Tanpa ini, dua request paralel bisa sama-sama
        # membaca counter lama lalu sama-sama menulis, sehingga kuota terlampaui
        # pada trafik yang justru paling ramai.
        self._locks: dict[str, asyncio.Lock] = {}

    def _lock_for(self, bucket: str) -> asyncio.Lock:
        lock = self._locks.get(bucket)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[bucket] = lock
        return lock

    def _key(self, bucket: str) -> str:
        r"""Kunci lengkap di memory store, termasuk prefiks store.

        Counter disimpan lewat API cache, jadi key sebenarnya sudah berawalan
        ``cache:``. Fungsi ini mengembalikan bentuk yang sudah lengkap supaya
        ``delete_by_prefix`` bisa mencocokkan; versi sebelumnya mengembalikan
        kunci tanpa prefiks, sehingga reset tidak pernah menghapus apa pun.
        """
        return f"{CACHE_PREFIX}{LIMIT_PREFIX}{bucket}"

    async def check(self, bucket: str) -> tuple[bool, int]:
        """Periksa dan catat satu pemakaian.

        Returns:
            ``(boleh, retry_after_detik)``. Kalau ``boleh`` False,
            ``retry_after`` memberi tahu berapa lama harus menunggu.
        """
        now = time.time()

        async with self._lock_for(bucket):
            raw = await self._store.get_cached(LIMIT_PREFIX + bucket)
            timestamps: list[float] = []
            if isinstance(raw, dict):
                stored = raw.get("hits")
                if isinstance(stored, list):
                    timestamps = [
                        float(item) for item in stored if isinstance(item, int | float)
                    ]

            recent = [stamp for stamp in timestamps if now - stamp < self._window]

            if len(recent) >= self._max:
                retry_after = max(1, int(self._window - (now - recent[0])) + 1)
                return False, retry_after

            recent.append(now)
            # TTL diset ke jendela penuh plus sedikit, supaya counter yang sudah
            # kedaluwarsa tidak menumpuk di memory store.
            await self._store.set_cached(
                LIMIT_PREFIX + bucket, {"hits": recent}, self._window + 5
            )
            return True, 0

    async def reset(self, bucket: str) -> None:
        await self._store.delete_by_prefix(self._key(bucket))
