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
    """Embedding deterministik memakai hashing trick, tanpa dependensi model.

    Bukan embedding semantik. Yang dilakukan adalah `hashing trick` klasik
    (seperti `HashingVectorizer`): setiap token di-hash ke satu slot dari 384
    dimensi, lalu slot itu ditambah satu. Cosine similarity dari dua vektor
    seperti ini **mendekati tumpang tindih token**: teks identik berskor 1.0,
    teks tanpa token bersama berskor ~0 (hanya tabrakan hash acak), dan teks
    yang berbagi separuh token berada di antaranya.

    Ini berbeda dari vektor bit yang dense (setiap token menyalakan separuh
    dimensi), yang membuat semua teks saling tumpang tindih sekitar 0.8.
    Desain dense itu sudah dicoba dan gagal diukur: "xyz abc qwerty" terhadap
    dokumen SOP berskor 0.84, hampir sama dengan pertanyaan sungguhan 0.94,
    sehingga ambang berapa pun tidak bisa memisahkan keduanya.

    Yang tetap belum ada: kemampuan menangkap parafrase. "batas tanggung
    jawab" dan "siapa yang bertanggung jawab" tetap tidak mirip, karena tidak
    ada token bersama. Untuk itu memang perlu model sungguhan.

    Dipakai sebagai fallback dan di test. Kalau aktif di produksi, kualitas
    jelas di bawah embedding sungguhan; statusnya dilaporkan lewat health.
    """

    name = "hashing-fallback"

    def __init__(self, dimension: int = 384) -> None:
        self.dimension = dimension
        self._cache: dict[str, list[float]] = {}

    def _hash_vector(self, text: str) -> list[float]:
        vector = [0.0] * self.dimension
        tokens = _TOKEN_RE.findall(text.lower())
        for token in tokens:
            digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
            slot = int.from_bytes(digest[:4], "big") % self.dimension
            # Tanpa tanda: slot hanya menghitung kehadiran. Tanda acak justru
            # menambah varians yang menenggelamkan sinyal overlap pada teks
            # pendek, persis kondisi chunk dan pertanyaan.
            vector[slot] += 1.0
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
        # Prefix asimetris hanya milik keluarga E5. Model lain (bge,
        # gte, MiniLM) dilatih tanpa prefix; menusuntiknya tidak menambah
        # kualitas, hanya menggeser teks yang di-encode.
        self._uses_e5_prefix = "e5" in settings.embedding_model.lower()
        self._lock = threading.Lock()

        # Dimensi dicek untuk **semua** model, bukan hanya keluarga E5.
        # Model non-E5 pun punya dimensi sendiri (bge-m3 1024, MiniLM 384),
        # dan nilai default di konfigurasi hanya cocok untuk model yang
        # dipakai saat ini. Salah dimensi membuat cosine similarity meledak
        # dan retrieval kosong tanpa pesan yang menjelaskan penyebabnya.
        probe = self._model.encode(
            ["probe"] if not self._uses_e5_prefix else ["query: probe"],
            normalize_embeddings=True,
            show_progress_bar=False,
            convert_to_numpy=True,
        )
        actual = int(probe[0].shape[0])
        if actual != self.dimension:
            raise ValueError(
                f"{settings.embedding_model} menghasilkan {actual} dimensi, "
                f"tidak {self.dimension}. Set EMBEDDING_DIMENSION={actual}."
            )

    def _encode(self, texts: list[str], is_query: bool) -> list[list[float]]:
        # Model Model E5 dilatih dengan prefix asimetris: dokumen diberi
        # "passage: " dan pertanyaan diberi "query: ". Menghapus prefix ini
        # menurunkan kualitas retrieval, jadi harus dijaga.
        if self._uses_e5_prefix:
            prefix = "query: " if is_query else "passage: "
            prepared = [f"{prefix}{text}" for text in texts]
        else:
            prepared = list(texts)
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
#: Kunci yang dipakai cache singleton. Model, dimensi, dan mode lokal ikut
#: masuk karena semuanya mengubah vektor yang dihasilkan; tanpa itu, test atau
#: reload konfigurasi diam-diam memakai provider milik konfigurasi lama.
_singleton_key: tuple[str, int, bool] | None = None


def embedding_provider_key(settings: Settings) -> tuple[str, int, bool]:
    return (
        settings.embedding_model,
        int(settings.embedding_dimension),
        settings.use_local_embedding,
    )


def build_embedding_provider(settings: Settings) -> EmbeddingProvider:
    """Bangun provider embedding, atau fallback kalau model tak tersedia."""
    global _provider_singleton, _singleton_key

    wanted = embedding_provider_key(settings)
    if _provider_singleton is not None and _singleton_key == wanted:
        return _provider_singleton

    with _singleton_lock:
        if _provider_singleton is not None and _singleton_key == wanted:
            return _provider_singleton

        if not settings.use_local_embedding:
            _provider_singleton = HashingEmbeddingProvider(settings.embedding_dimension)
            _singleton_key = wanted
            return _provider_singleton

        try:
            _provider_singleton = SentenceTransformerEmbeddingProvider(settings)
            logger.info("Embedding provider: %s", settings.embedding_model)
        except Exception as exc:  # noqa: BLE001
            # Model gagal dimuat, misal offline atau paket belum terpasang.
            # Sistem tetap jalan dengan kualitas retrieval yang lebih rendah,
            # dan health endpoint melaporkan hal ini sebagai mode terbatas.
            logger.warning(
                "Embedding model %s gagal dimuat (%s). "
                "Memakai hashing fallback: retrieval hanya cocok untuk kata identik.",
                settings.embedding_model,
                exc,
            )
            _provider_singleton = HashingEmbeddingProvider(settings.embedding_dimension)
        _singleton_key = wanted
        return _provider_singleton


def reset_embedding_provider() -> None:
    """Bersihkan singleton. Dipakai test."""
    global _provider_singleton, _singleton_key
    with _singleton_lock:
        _provider_singleton = None
        _singleton_key = None
