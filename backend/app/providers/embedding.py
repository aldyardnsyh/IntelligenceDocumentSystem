"""Provider embedding lokal.

Embedding adalah bagian pipeline yang paling sering disalahpahami biayanya:
modelnya cuma ~90 MB, jalan di CPU, nol biaya, dan **data tidak keluar dari
mesin**. Jadi tidak ada alasan memindahkannya ke API. Yang mahal adalah
generation, bukan ini.
"""

from __future__ import annotations

import hashlib
import logging
import re
import threading
from typing import Protocol, runtime_checkable

from app.core.config import Settings

logger = logging.getLogger(__name__)

_TOKEN_RE = re.compile(r"[a-z0-9]+")


@runtime_checkable
class EmbeddingProvider(Protocol):
    """Antarmuka embedding."""

    name: str
    dimension: int

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        ...

    def embed_query(self, text: str) -> list[float]:
        ...


class HashingEmbeddingProvider:
    """Embedding deterministik berbasis hashing, tanpa dependensi model.

    Bukan embedding semantik: vektor ini hanya bisa mencocokkan kata yang
    identik. Dipakai sebagai fallback ketika sentence-transformers belum
    terpasang, dan di test yang tidak butuh semantik.

    Penting untuk disebut terang-terang: kalau provider ini aktif di
    produksi, kualitas retrieval anjlok jauh di bawah embedding sungguhan.
    Statusnya dilaporkan lewat ``/api/v1/health`` supaya tidak terlihat seola-ola
    sistem yang bekerja penuh.
    """

    name = "hashing-fallback"

    def __init__(self, dimension: int = 384) -> None:
        self.dimension = dimension
        self._cache: dict[str, list[float]] = {}

    def _token_vector(self, token: str) -> list[float]:
        """Vektor dense dari bit-bit hash satu token.

        Serat nilai biner, bukan acak bertanda. Karena setiap bit selalu
        ``+1``, dua token yang berbeda tetap menghasilkan tumpang tindih
        positif pada slot yang sama, sehingga cosine similarity antar teks
        mencerminkan tumpang tindih token, bukan mendekati nol.
        """
        digest = hashlib.blake2b(token.encode("utf-8"), digest_size=32).digest()
        bits = int.from_bytes(digest, "big")
        return [1.0 if (bits >> position) & 1 else 0.0 for position in range(self.dimension)]

    def _hash_vector(self, text: str) -> list[float]:
        vector = [0.0] * self.dimension
        tokens = _TOKEN_RE.findall(text.lower())
        for token in tokens:
            token_vector = self._token_vector(token)
            for position, value in enumerate(token_vector):
                vector[position] += value
        norm = sum(value * value for value in vector) ** 0.5
        if norm == 0.0:
            return vector
        return [value / norm for value in vector]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self.embed_query(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        cached = self._cache.get(text)
        if cached is not None:
            return cached
        vector = self._hash_vector(text)
        # Cache dibatasi supaya jangan menumpuk tanpa batas pada server yang
        # hidup lama.
        if len(self._cache) < 2048:
            self._cache[text] = vector
        return vector


class SentenceTransformerEmbeddingProvider:
    """Embedding sungguhan via sentence-transformers.

    Default model-nya multilingual karena dokumen dan pertanyaan berbahasa
    Indonesia. Model Inggris-first seperti all-MiniLM-L6-v2 menghasilkan vektor
    yang jauh lebih buruk untuk Bahasa Indonesia, dan pengaruhnya ke
    recall_at_5 bisa turun tajam.
    """

    name = "sentence-transformers"

    def __init__(self, settings: Settings) -> None:
        from sentence_transformers import SentenceTransformer  # noqa: PLC0415

        self._settings = settings
        self._model_name = settings.embedding_model
        self._model = SentenceTransformer(settings.embedding_model, device="cpu")
        self.dimension = int(settings.embedding_dimension)
        self._lock = threading.Lock()

    def _encode(self, texts: list[str], is_query: bool) -> list[list[float]]:
        # Model Model E5 dilatih dengan prefix asimetris: dokumen diberi
        # "passage: " dan pertanyaan diberi "query: ". Menghilangan prefix ini
        # menurunkan kualitas retrieval, jadi harus dijaga.
        prefix = "query: " if is_query else "passage: "
        prepared = [f"{prefix}{text}" for text in texts]
        vectors = self._model.encode(
            prepared,
            batch_size=self._settings.embedding_batch_size,
            normalize_embeddings=True,
            show_progress_bar=False,
            convert_to_numpy=True,
        )
        return [vector.tolist() for vector in vectors]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        with self._lock:
            return self._encode(texts, is_query=False)

    def embed_query(self, text: str) -> list[float]:
        with self._lock:
            return self._encode([text], is_query=True)[0]


_provider_singleton: EmbeddingProvider | None = None
_singleton_lock = threading.Lock()


def build_embedding_provider(settings: Settings) -> EmbeddingProvider:
    """Bangun provider embedding, atau fallback kalau model tak tersedia."""
    global _provider_singleton

    if _provider_singleton is not None:
        return _provider_singleton

    with _singleton_lock:
        if _provider_singleton is not None:
            return _provider_singleton

        if not settings.use_local_embedding:
            _provider_singleton = HashingEmbeddingProvider(settings.embedding_dimension)
            return _provider_singleton

        try:
            _provider_singleton = SentenceTransformerEmbeddingProvider(settings)
            logger.info("Embedding provider: %s", settings.embedding_model)
        except Exception as exc:  # noqa: BLE001
            # Model gagal dimuat, misal offline atau paket belum terpasang.
            # Sistem tetap jalan dengan kualitas retrieval yang lebih rendah,
            # dan health endpoint akan melaporkan hal ini.
            logger.warning(
                "Embedding model %s gagal dimuat (%s). "
                "Memakai hashing fallback: retrieval hanya cocok untuk kata identik.",
                settings.embedding_model,
                exc,
            )
            _provider_singleton = HashingEmbeddingProvider(settings.embedding_dimension)
        return _provider_singleton


def reset_embedding_provider() -> None:
    """Bersihkan singleton. Dipakai test."""
    global _provider_singleton
    with _singleton_lock:
        _provider_singleton = None
