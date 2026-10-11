"""Memory store: histori percakapan dan cache query.

Ada dua backend:

- **Redis** (atau Upstash REST) untuk deployment multi-instance, sesuai PRD 7.
- **Dict in-process** untuk pengembangan lokal dan test.

Pemilihan otomatis berdasarkan env. Kalau Redis tidak ada, sistem tetap jalan
dan dilaporkan lewat health endpoint, bukan diam-diam berperilaku seolah-olah
sesi tersimpan selamanya.
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
from typing import Protocol, runtime_checkable

from app.core.config import Settings
from app.models.domain import ChatMessage, MessageRole

logger = logging.getLogger(__name__)

MEMORY_PREFIX = "chat:"
CACHE_PREFIX = "cache:"
#: Namespace cache jawaban RAG. Dipisah dari counter rate limit supaya
#: menghapus cache (mis. saat dokumen dihapus) tidak ikut mereset kuota.
ANSWER_CACHE_PREFIX = "answer:"


@runtime_checkable
class MemoryStore(Protocol):
    """Antarmuka memory dan cache.

    Semua method sengaja ``async``, termasuk untuk store in-process yang
    kerjanya sebenarnya sinkron. Alasannya bukan gaya penulisan, tapi
    konsistensi: pemanggil selalu menulis ``await``, jadi ketika
    ``InMemoryStore`` (sinkron) dan ``RedisStore`` (asinkron) dipakai
    bergantian, persis yang terjadi saat Redis gagal dan sistem jatuh ke
    fallback, pemanggil yang lupa ``await`` akan gagal dengan ``TypeError:
    object NoneType can't be used in 'await' expression``, yaitu persis di
    jalur yang paling penting justru saat ada masalah. ``InMemoryStore``
    karena itu membungkus method sinkronnya dengan fungsi async tipis.
    """

    name: str
    persistent: bool

    async def save_session(
        self, session_id: str, messages: list[dict[str, object]], ttl: int
    ) -> None:
        ...

    async def load_session(self, session_id: str) -> list[dict[str, object]] | None:
        ...

    async def delete_session(self, session_id: str) -> None:
        ...

    async def list_sessions(self) -> list[str]:
        """ID sesi yang masih hidup, untuk sidebar."""
        ...

    async def get_cached(self, key: str) -> dict[str, object] | None:
        ...

    async def set_cached(self, key: str, value: dict[str, object], ttl: int) -> None:
        ...

    async def delete_by_prefix(self, prefix: str) -> int:
        ...

    async def ping(self) -> bool:
        """True kalau store bisa dihubungi."""
        ...


class InMemoryStore:
    """Store in-process dengan expiry sederhana.

    Cukup untuk pengembangan dan test. Kelemahannya: hilang saat restart, dan
    tidak dibagi antar instance.

    Method publiknya ``async`` meski tidak ada I/O, supaya bisa menggantikan
    ``RedisStore`` tanpa pemanggil perlu tahu bedanya. Karena pemanggil boleh
    memanggilnya lewat ``asyncio.to_thread`` (parsing, agregasi), akses ke dict
    dijaga lock: dict yang dibaca dan ditulis dari dua thread bisa/runtimeerror.
    """

    name = "in-memory"
    persistent = False

    def __init__(self) -> None:
        self._values: dict[str, tuple[float, dict[str, object] | list[dict[str, object]]]] = {}
        self._lock = threading.Lock()

    def _expired(self, key: str, now: float) -> bool:
        entry = self._values.get(key)
        if entry is None:
            return True
        return entry[0] < now

    def _sweep(self, now: float) -> None:
        """Buang entri kedaluwarsa.

        Tanpa ini dict hanya pernah dibersihkan saat key yang sama dibaca
        lagi, jadi kunci yang tidak pernah diakses lagi tetap menumpuk sampai
        server restart.
        """
        expired = [key for key, (deadline, _value) in self._values.items() if deadline < now]
        for key in expired:
            self._values.pop(key, None)

    def _write(
        self, key: str, value: dict[str, object] | list[dict[str, object]], ttl: int
    ) -> None:
        with self._lock:
            self._values[key] = (time.time() + ttl, value)

    def _read(self, key: str) -> dict[str, object] | list[dict[str, object]] | None:
        with self._lock:
            if self._expired(key, time.time()):
                self._values.pop(key, None)
                return None
            return self._values[key][1]

    async def save_session(
        self, session_id: str, messages: list[dict[str, object]], ttl: int
    ) -> None:
        self._write(f"{MEMORY_PREFIX}{session_id}", messages, ttl)

    async def load_session(self, session_id: str) -> list[dict[str, object]] | None:
        value = self._read(f"{MEMORY_PREFIX}{session_id}")
        return value if isinstance(value, list) else None

    async def delete_session(self, session_id: str) -> None:
        with self._lock:
            self._values.pop(f"{MEMORY_PREFIX}{session_id}", None)

    async def list_sessions(self) -> list[str]:
        now = time.time()
        with self._lock:
            self._sweep(now)
            return [
                key[len(MEMORY_PREFIX) :]
                for key, (expires_at, _value) in list(self._values.items())
                if key.startswith(MEMORY_PREFIX) and expires_at >= now
            ]

    async def get_cached(self, key: str) -> dict[str, object] | None:
        value = self._read(f"{CACHE_PREFIX}{key}")
        return value if isinstance(value, dict) else None

    async def set_cached(self, key: str, value: dict[str, object], ttl: int) -> None:
        self._write(f"{CACHE_PREFIX}{key}", value, ttl)

    async def delete_by_prefix(self, prefix: str) -> int:
        with self._lock:
            keys = [key for key in self._values if key.startswith(prefix)]
            for key in keys:
                self._values.pop(key, None)
            return len(keys)

    async def ping(self) -> bool:
        return True


class RedisStore:
    """Redis asyncio, untuk deployment dengan lebih dari satu instance."""

    name = "redis"
    persistent = True

    def __init__(self, url: str) -> None:
        from redis.asyncio import Redis  # noqa: PLC0415

        self._client = Redis.from_url(url, decode_responses=True)
        self._scan_batch = 200

    async def save_session(
        self, session_id: str, messages: list[dict[str, object]], ttl: int
    ) -> None:
        await self._client.set(f"{MEMORY_PREFIX}{session_id}", json.dumps(messages), ex=ttl)

    async def load_session(self, session_id: str) -> list[dict[str, object]] | None:
        raw = await self._client.get(f"{MEMORY_PREFIX}{session_id}")
        if raw is None:
            return None
        try:
            decoded = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("Isi sesi %s rusak, dianggap tidak ada.", session_id)
            return None
        return decoded if isinstance(decoded, list) else None

    async def delete_session(self, session_id: str) -> None:
        await self._client.delete(f"{MEMORY_PREFIX}{session_id}")

    async def list_sessions(self) -> list[str]:
        # SCAN, bukan KEYS: KEYS memblokir server Redis pada database besar.
        found: list[str] = []
        cursor = 0
        while True:
            cursor, keys = await self._client.scan(
                cursor=cursor, match=f"{MEMORY_PREFIX}*", count=self._scan_batch
            )
            found.extend(key[len(MEMORY_PREFIX) :] for key in keys)
            if cursor == 0:
                break
        return found

    async def get_cached(self, key: str) -> dict[str, object] | None:
        raw = await self._client.get(f"{CACHE_PREFIX}{key}")
        if raw is None:
            return None
        try:
            decoded = json.loads(raw)
        except json.JSONDecodeError:
            return None
        return decoded if isinstance(decoded, dict) else None

    async def set_cached(self, key: str, value: dict[str, object], ttl: int) -> None:
        await self._client.set(f"{CACHE_PREFIX}{key}", json.dumps(value), ex=ttl)

    async def delete_by_prefix(self, prefix: str) -> int:
        deleted = 0
        cursor = 0
        pattern = f"{prefix}*"
        while True:
            cursor, keys = await self._client.scan(
                cursor=cursor, match=pattern, count=self._scan_batch
            )
            if keys:
                deleted += int(await self._client.delete(*keys))
            if cursor == 0:
                break
        return deleted

    async def ping(self) -> bool:
        try:
            return bool(await self._client.ping())
        except Exception:  # noqa: BLE001
            return False


_store: MemoryStore | None = None


def build_memory_store(settings: Settings) -> MemoryStore:
    """Bangun memory store sesuai konfigurasi.

    Upstash ikut dibaca: operator sering hanya mengisi
    ``UPSTASH_REDIS_URL`` + ``UPSTASH_REDIS_TOKEN`` karena itu yang diberikan
    konsolnya. Versi sebelumnya mengabaikan keduanya, jadi store tetap
    in-memory sementara health melaporkan mode yang meyakinkan.
    """
    global _store
    if _store is not None:
        return _store

    redis_url = settings.redis_url or upstash_redis_url(settings)
    if redis_url:
        try:
            _store = RedisStore(redis_url)
            logger.info("Memory store: Redis")
        except Exception as exc:  # noqa: BLE001
            logger.warning("Redis tidak bisa dipakai (%s), memakai store in-memory.", exc)
            _store = InMemoryStore()
    else:
        _store = InMemoryStore()
        logger.info("Memory store: in-memory (sesi hilang saat restart)")
    return _store


def upstash_redis_url(settings: Settings) -> str | None:
    """Bentuk URL Redis dari kredensial Upstash, kalau keduanya diisi.

    Password Upstash adalah bagian kredensial, jadi tidak pernah dicatat ke log
    bersama URL yang sudah jadi.
    """
    host = (settings.upstash_redis_url or "").strip()
    token = (settings.upstash_redis_token or "").strip()
    if not host or not token:
        return None
    if host.startswith(("redis://", "rediss://")):
        return host
    scheme = "rediss" if ".upstash.io" in host else "redis"
    return f"{scheme}://default:{token}@{host}"


def reset_memory_store() -> None:
    """Bersihkan singleton. Dipakai test."""
    global _store
    _store = None


def message_to_dict(message: ChatMessage) -> dict[str, object]:
    """Serialisasi pesan untuk storage."""
    from app.models.schemas import message_to_response  # noqa: PLC0415

    return message_to_response(message).model_dump(mode="json")


def dict_to_message(payload: dict[str, object]) -> ChatMessage:
    """Bangun pesan dari data storage."""
    from app.models.domain import Citation  # noqa: PLC0415

    raw_citations = payload.get("citations")
    # Yang dibangun di sini adalah `Citation` domain, bukan model respons API.
    # `ChatMessage.citations` dideklarasikan `list[Citation]`, dan mencampur
    # tipe respons ke sana membuat konsumen yang memanggil `.model_dump()`
    # gagal hanya pada beberapa jalur.
    citations = [
        Citation(
            document_id=str(item.get("document_id", "")),
            document_name=str(item.get("document_name", "")),
            page_number=(
                item.get("page_number")
                if isinstance(item.get("page_number"), int)
                else None
            ),
            chunk_index=int(item.get("chunk_index", 0)),
            excerpt=str(item.get("excerpt", "")),
            score=float(item.get("score", 0.0)),
        )
        for item in (raw_citations if isinstance(raw_citations, list) else [])
        if isinstance(item, dict)
    ]

    return ChatMessage(
        id=str(payload.get("id", "")),
        role=MessageRole(str(payload.get("role", "user"))),
        content=str(payload.get("content", "")),
        created_at=str(payload.get("created_at", "")),
        citations=citations,
        not_found=bool(payload.get("not_found", False)),
        ungrounded=bool(payload.get("ungrounded", False)),
    )


def cache_key(
    question: str,
    document_ids: list[str] | None,
    top_k: int,
    similarity_threshold: float | None = None,
    document_id: str | None = None,
) -> str:
    """Kunci cache query (FR-4.1).

    Hash dari query, set dokumen, dan parameter retrieval. Semua yang bisa
    mengubah jawaban harus ikut: ``top_k`` menentukan berapa sumber yang
    diambil, ``similarity_threshold`` menentukan apakah retrieval lolos gate
    sama sekali, dan ``document_id`` menentukan dokumen mana yang boleh
    dicari. Tanpa scope di kunci ini, sesi privat dokumen A bisa menyajikan
    jawaban yang dibuat dari dokumen B, kebocoran yang tidak terlihat di UI.

    Prefix ``answer:`` dipakai supaya cache jawaban bisa dihapus tanpa ikut
    menghapus counter rate limit, yang kebetulan tinggal di namespace cache
    yang sama.
    """
    payload = json.dumps(
        {
            "question": question.strip().lower(),
            "documents": sorted(document_ids or []),
            "top_k": top_k,
            "threshold": similarity_threshold,
            "scope": document_id,
        },
        sort_keys=True,
    )
    return f"{ANSWER_CACHE_PREFIX}{hashlib.sha256(payload.encode('utf-8')).hexdigest()}"
