"""Rate limit terdistribusi via memory store.

Rate limit per sesi dibutuhkan untuk melindungi kuota free tier. Batas per IP
saja tidak cukup: satu orang bisa membuka banyak sesi, atau satu sesi dipakai
beberapa orang sekaligus. Batas per sesi menutup kedua kasus itu.
"""

from __future__ import annotations

from app.core.config import Settings
from app.services.memory.store import CACHE_PREFIX, MemoryStore

LIMIT_PREFIX = "ratelimit:"


class RateLimiter:
    """Sliding window counter yang disimpan di memory store.

    Berbeda dengan limiter in-process di ``core.security``, yang ini terbagi
    antar instance, karena state-nya ada di memory store bersama (Redis).

    Baca-ubah-tulis counter dilakukan oleh ``store.hit_sliding_window``, bukan
    di kelas ini. Versi sebelumnya memakai ``asyncio.Lock`` per bucket lalu
    memanggil ``get_cached`` dan ``set_cached`` secara terpisah. Lock itu hanya
    menjaga satu proses: begitu aplikasi berjalan di dua instance, keduanya
    punya lock sendiri yang tidak saling tahu, dan keduanya bisa membaca
    counter yang sama sebelum salah satunya menulis. Akibatnya batas terlewati
    tepat pada trafik yang paling ramai. Dengan operasi atomik di store, satu
    skrip Lua di Redis, jaminannya berlaku lintas instance.
    """

    def __init__(self, store: MemoryStore, settings: Settings) -> None:
        self._store = store
        self._max = settings.query_max_per_session
        self._window = settings.query_window_seconds

    def _key(self, bucket: str) -> str:
        r"""Kunci di memory store, tanpa prefiks cache.

        Prefiks ``cache:`` ditambahkan oleh store sendiri, jadi kunci di sini
        tidak boleh ikut memuatnya. Versi sebelumnya mengembalikan bentuk yang
        sudah berprefiks untuk keperluan ``delete_by_prefix``; sekarang
        ``reset`` menghapus kunci persisnya, sehingga prefiks ganda akan
        membuat reset gagal menghapus apa pun.
        """
        return f"{LIMIT_PREFIX}{bucket}"

    def _key_lengkap(self, bucket: str) -> str:
        """Kunci lengkap termasuk prefiks store, untuk operasi hapus massal."""
        return f"{CACHE_PREFIX}{self._key(bucket)}"

    async def check(self, bucket: str) -> tuple[bool, int]:
        """Periksa dan catat satu pemakaian.

        Returns:
            ``(boleh, retry_after_detik)``. Kalau ``boleh`` False,
            ``retry_after`` memberi tahu berapa lama harus menunggu.
        """
        return await self._store.hit_sliding_window(
            self._key(bucket), self._max, self._window
        )

    async def reset(self, bucket: str) -> None:
        await self._store.delete_by_prefix(self._key_lengkap(bucket))
