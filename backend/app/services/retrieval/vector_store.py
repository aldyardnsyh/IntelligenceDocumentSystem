"""Vector store dengan cosine similarity.

Dipakai Chroma kalau tersedia, dan in-memory store kalau tidak. Keduanya
mengimplementasikan ``VectorStore``, jadi pipeline tidak tahu bedanya.

Kenapa ada fallback in-memory: portofolio harus bisa dijalankan tanpa satu
pun akun cloud, dan test harus bisa jalan tanpa menunggu Chroma selesai
startup. Tapi perlu jujur: store in-memory kehilangan vektor setiap restart,
sehingga untuk demo multi-sesi, indeksnya hilang. Itu dilaporkan lewat health
endpoint, bukan disembunyikan.
"""

from __future__ import annotations

import logging
import math
import threading
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from app.core.config import Settings

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class VectorRecord:
    """Satu vektor beserta metadata yang menyertainya."""

    id: str
    embedding: list[float]
    metadata: dict[str, str | int | float | None]


@runtime_checkable
class VectorStore(Protocol):
    """Antarmuka vector store."""

    name: str
    persistent: bool

    def upsert(self, records: Iterable[VectorRecord], collection: str) -> None:
        ...

    def query(
        self,
        embedding: list[float],
        collection: str,
        top_k: int,
        where: dict[str, object] | None = None,
    ) -> list[tuple[str, float, dict[str, object]]]:
        """Kembalikan ``(id, cosine_similarity, metadata)`` terurut menurun."""
        ...

    def delete_document(self, document_id: str, collection: str) -> int:
        """Hapus hanya vektor milik satu dokumen. Kembalikan jumlah yang dihapus.

        Dipisah dari ``delete_collection`` karena menghapus dokumen satu
        tidak boleh ikut menghapus dokumen lain yang sudah terindeks.
        """
        ...

    def delete_collection(self, collection: str) -> None:
        ...

    def count(self, collection: str) -> int:
        ...

    def ping(self) -> bool:
        """True kalau store bisa dihubungi. Dipakai health endpoint."""
        ...


def cosine_similarity(left: list[float], right: list[float]) -> float:
    """Cosine similarity dua vektor.

    Normalisasi dilakukan di sini, bukan diasumsikan, supaya store in-memory
    dan Chroma menghitung angka yang sama. Cosine similarity didefinisikan ulang
    karena numpy tidak jadi dependensi wajib: vektornya cuma beberapa ratus
    dimensi per chunk, jadi perkalian skalar cukup cepat.
    """
    if len(left) != len(right):
        raise ValueError(
            f"Dimensi vektor tidak sama: {len(left)} != {len(right)}. "
            "Kemungkinan model embedding berganti setelah dokumen diindeks."
        )
    dot = 0.0
    left_sq = 0.0
    right_sq = 0.0
    for a, b in zip(left, right, strict=True):
        dot += a * b
        left_sq += a * a
        right_sq += b * b
    if left_sq == 0.0 or right_sq == 0.0:
        return 0.0
    return dot / (math.sqrt(left_sq) * math.sqrt(right_sq))


class InMemoryVectorStore:
    """Vector store in-process.

    Cocok untuk test dan demo sekali jalan. Data hilang saat proses berhenti.
    """

    name = "in-memory"
    persistent = False

    def __init__(self) -> None:
        self._data: dict[str, dict[str, VectorRecord]] = {}
        self._lock = threading.Lock()

    def upsert(self, records: Iterable[VectorRecord], collection: str) -> None:
        with self._lock:
            bucket = self._data.setdefault(collection, {})
            for record in records:
                bucket[record.id] = record

    def query(
        self,
        embedding: list[float],
        collection: str,
        top_k: int,
        where: dict[str, object] | None = None,
    ) -> list[tuple[str, float, dict[str, object]]]:
        with self._lock:
            bucket = dict(self._data.get(collection, {}))

        scored: list[tuple[str, float, dict[str, object]]] = []
        for record in bucket.values():
            if where and not _matches(record.metadata, where):
                continue
            try:
                score = cosine_similarity(embedding, record.embedding)
            except ValueError:
                # Vektor berdimensi berbeda: lewati, jangan gagalkan seluruh query.
                continue
            scored.append((record.id, score, dict(record.metadata)))

        scored.sort(key=lambda item: item[1], reverse=True)
        return scored[:top_k]

    def delete_document(self, document_id: str, collection: str) -> int:
        with self._lock:
            bucket = self._data.get(collection, {})
            doomed = [
                identifier
                for identifier, record in bucket.items()
                if record.metadata.get("document_id") == document_id
            ]
            for identifier in doomed:
                bucket.pop(identifier, None)
        return len(doomed)

    def delete_collection(self, collection: str) -> None:
        with self._lock:
            self._data.pop(collection, None)

    def count(self, collection: str) -> int:
        with self._lock:
            return len(self._data.get(collection, {}))

    def ping(self) -> bool:
        # Store in-process tidak punya I/O, jadi selalu bisa dihubungi.
        return True


def _matches(metadata: dict[str, object], where: dict[str, object]) -> bool:
    """Filter metadata sederhana dengan dukungan ``$in``."""
    for key, expected in where.items():
        actual = metadata.get(key)
        if isinstance(expected, dict) and "$in" in expected:
            allowed = expected["$in"]
            if isinstance(allowed, (list, tuple, set)) and actual not in allowed:
                return False
        elif actual != expected:
            return False
    return True


class ChromaVectorStore:
    """ChromaDB dengan persistensi lokal."""

    name = "chroma"
    persistent = True

    def __init__(self, settings: Settings) -> None:
        import chromadb
        from chromadb.config import Settings as ChromaSettings

        self._client = chromadb.PersistentClient(
            path=settings.chroma_persist_dir,
            settings=ChromaSettings(anonymized_telemetry=False),
        )
        self._lock = threading.Lock()

    def _collection(self, collection: str):  # noqa: ANN202 - tipe internal dari Chroma
        return self._client.get_or_create_collection(
            name=collection,
            metadata={"hnsw:space": "cosine"},
        )

    def upsert(self, records: Iterable[VectorRecord], collection: str) -> None:
        batch = list(records)
        if not batch:
            return
        with self._lock:
            handle = self._collection(collection)
            handle.upsert(
                ids=[record.id for record in batch],
                embeddings=[record.embedding for record in batch],
                documents=[str(record.metadata.get("content", "")) for record in batch],
                metadatas=[_clean_metadata(record.metadata) for record in batch],
            )

    def query(
        self,
        embedding: list[float],
        collection: str,
        top_k: int,
        where: dict[str, object] | None = None,
    ) -> list[tuple[str, float, dict[str, object]]]:
        with self._lock:
            handle = self._collection(collection)
            if handle.count() == 0:
                return []
            # Chroma mengembalikan jarak, bukan kemiripan. Cosine distance 0
            # berarti identik, jadi similarity = 1 - distance.
            result = handle.query(
                query_embeddings=[embedding],
                n_results=top_k,
                where=where or None,
                include=["metadatas", "distances"],
            )

        ids = (result.get("ids") or [[]])[0]
        distances = (result.get("distances") or [[]])[0]
        metadatas = (result.get("metadatas") or [[]])[0]

        rows: list[tuple[str, float, dict[str, object]]] = []
        for index, identifier in enumerate(ids):
            distance = float(distances[index]) if index < len(distances) else 1.0
            metadata = metadatas[index] if index < len(metadatas) else {}
            rows.append((identifier, max(0.0, 1.0 - distance), dict(metadata or {})))
        return rows

    def delete_document(self, document_id: str, collection: str) -> int:
        with self._lock:
            try:
                handle = self._collection(collection)
                # Count dulu supaya hasilnya Jujur: Chroma tidak mengembalikan
                # jumlah baris yang terhapus.
                before = handle.count()
                handle.delete(where={"document_id": document_id})
                return max(0, before - handle.count())
            except Exception:  # noqa: BLE001
                logger.exception("Gagal menghapus vektor dokumen %s", document_id)
                return 0

    def delete_collection(self, collection: str) -> None:
        with self._lock:
            try:
                self._client.delete_collection(name=collection)
            except ValueError:
                # Koleksi belum pernah dibuat; tidak apa-apa.
                logger.debug("Koleksi %s belum ada saat dihapus.", collection)

    def count(self, collection: str) -> int:
        with self._lock:
            try:
                return self._collection(collection).count()
            except Exception:  # noqa: BLE001
                return 0

    def ping(self) -> bool:
        """Cek koneksi ke Chroma tanpa membuat koleksi apa pun.

        Versi lama memakai ``get_or_create_collection("__ping__")`` dan itu
        pecah di Chroma 1.x: binding Rust-nya menolak nama yang diawali atau
        diakhiri underscore, sehingga health selalu "unreachable" padahal
        Chroma sehat. ``heartbeat()`` tidak menyentuh koleksi sama sekali.
        """
        with self._lock:
            try:
                self._client.heartbeat()
                return True
            except Exception:  # noqa: BLE001
                logger.exception("Chroma tidak bisa dihubungi")
                return False


def _clean_metadata(
    metadata: dict[str, str | int | float | None],
) -> dict[str, str | int | float | bool]:
    """Chroma hanya menerima nilai skalar, dan ``None`` ditolak.

    Metadata ``None`` diubah jadi string kosong supaya filter tetap bisa
    dipakai, nilai bool disimpan sebagai bool karena Chroma sekarang menerimanya.
    """
    cleaned: dict[str, str | int | float | bool] = {}
    for key, value in metadata.items():
        if value is None:
            cleaned[key] = ""
        elif isinstance(value, (str, int, float, bool)):
            cleaned[key] = value
        else:
            cleaned[key] = str(value)
    return cleaned


_store: VectorStore | None = None
_store_lock = threading.Lock()


def build_vector_store(settings: Settings) -> VectorStore:
    """Bangun vector store persisten, atau in-memory kalau Chroma gagal."""
    global _store
    if _store is not None:
        return _store

    with _store_lock:
        if _store is not None:
            return _store
        try:
            _store = ChromaVectorStore(settings)
            logger.info("Vector store: Chroma (%s)", settings.chroma_persist_dir)
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "Chroma tidak bisa dipakai (%s). Memakai store in-memory: "
                "indeks hilang setiap restart dan seluruh koleksi dipindai "
                "linear per query, jadi ukurannya harus tetap kecil.",
                exc,
                exc_info=True,
            )
            _store = InMemoryVectorStore()
        return _store


def reset_vector_store() -> None:
    """Bersihkan singleton. Dipakai test."""
    global _store
    with _store_lock:
        _store = None
