"""Retrieval hybrid: vektor semantik + BM25 leksikal.

Kenapa hybrid, bukan salah satu saja:

- **Vektor saja** gagal pada kata kunci spesifik: nomor klausul, nama
  perusahaan, kode produk. Embedding "bagaimana cara membatalkan kontrak
  nomor INV-2024-0812" tidak akan dekat dengan chunk yang memuat nomor itu
  persis, karena vektor menangkap makna umum, bukan token spesifik.
- **BM25 saja** gagal pada parafrase: dokumen menulis "batas tanggung jawab"
  sementara pertanyaan menyebut "siapa yang bertanggung jawab". Tidak ada
  kata yang sama, jadi skor BM25-nya nol, padahal maknanya sama.

Gabungan keduanya menutup dua lubang itu. Ini bukan ide baru, tapi sering
dilewati karena lebih banyak kode daripada memanggil satu fungsi.

Skor akhir adalah **reciprocal rank fusion**, bukan penjumlahan skor mentah.
Alasannya: skor cosine (0..1) dan skor BM25 (0.. tak terbatas) tidak
sebanding, jadi menjumlahkannya berarti salah satu selalu mendominasi.
RRF hanya melihat peringkat, yang selalu sebanding.
"""

from __future__ import annotations

import logging
import math
from collections import Counter, defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

from app.models.domain import Chunk, RetrievedChunk
from app.services.retrieval.text_processing import tokenize_for_search
from app.services.retrieval.vector_store import VectorStore

if TYPE_CHECKING:
    from app.services.retrieval.reranker import Reranker

logger = logging.getLogger(__name__)

COLLECTION = "chunks"

#: Bobot RRF. Vektor diberi bobot sedikit lebih tinggi karena lebih baik
#: menangkap maksud, sementara BM25 menangkap kelengkapan.
RRF_K = 60
VECTOR_WEIGHT = 1.0
KEYWORD_WEIGHT = 0.6


def tokenize(text: str) -> list[str]:
    """Token BM25: huruf kecil, tanpa stop word, bentuk dasar Sastrawi.

    Logika lengkapnya ada di ``text_processing.tokenize_for_search``; fungsi
    ini jembatan supaya pemanggil lama dan test tidak perlu berubah. Angka satu
    digit sengaja dipertahankan ("pasal 2" adalah rujukan yang spesifik), dan
    stemming dijalankan seragam untuk dokumen maupun query supaya keduanya
    bertemu di kosakata yang sama.
    """
    return tokenize_for_search(text)


@dataclass(slots=True)
class KeywordIndex:
    """Indeks BM25 dengan inverted index.

    Strukturnya: ``postings[token]`` berisi id chunk yang memuat token itu,
    dan ``doc_freqs[chunk_id]`` berisi frekuensi per token. Pencarian hanya
    menyusuri postingan token yang diminta, bukan memindai seluruh chunk:
    pada korpus ribuan chunk ini bedanya detik menentukan. Kalau korpusnya
    tumbuh jadi ratusan ribu chunk, indeks ini perlu dipindah ke mesin
    pencarian khusus (Meilisearch, Elasticsearch), tapi untuk skala di sini
    in-memory inverted index sudah tepat.
    """

    doc_freqs: dict[str, Counter[str]] = None  # type: ignore[assignment]
    doc_lengths: dict[str, int] = None  # type: ignore[assignment]
    postings: dict[str, set[str]] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.doc_freqs is None:
            self.doc_freqs = {}
        if self.doc_lengths is None:
            self.doc_lengths = {}
        if self.postings is None:
            self.postings = {}

    @property
    def average_length(self) -> float:
        if not self.doc_lengths:
            return 0.0
        return sum(self.doc_lengths.values()) / len(self.doc_lengths)

    def add(self, document_id: str, content: str) -> None:
        """Tambahkan satu chunk ke indeks kata.

        Kalau id-nya sudah ada, konten lama dibuang dulu supaya postingan
        tidak menghitung chunk yang sama dua kali.
        """
        tokens = tokenize(content)
        frequency = Counter(tokens)
        if document_id in self.doc_freqs:
            self.remove(document_id)
        self.doc_freqs[document_id] = frequency
        self.doc_lengths[document_id] = len(tokens)
        for token in frequency:
            self.postings.setdefault(token, set()).add(document_id)

    def remove(self, document_id: str) -> None:
        """Buang satu chunk dari indeks. Aman kalau id-nya tidak ada."""
        frequency = self.doc_freqs.pop(document_id, None)
        if frequency is None:
            return
        for token in frequency:
            group = self.postings.get(token)
            if group is None:
                continue
            group.discard(document_id)
            if not group:
                del self.postings[token]
        self.doc_lengths.pop(document_id, None)

    def search(
        self,
        query: str,
        top_k: int,
        allowed_ids: set[str] | None = None,
    ) -> list[tuple[str, float]]:
        """BM25 dengan parameter standar k1=1.5, b=0.75.

        Args:
            query: Pertanyaan pengguna; tokenisasi dijalankan di sini dengan
                pemroses yang sama dengan yang membangun indeks.
            top_k: Berapa banyak hasil yang dikembalikan.
            allowed_ids: Batasi hanya id chunk milik dokumen yang diminta. Tanpa
                filter ini, kandidat yang mengisi ``top_k`` bisa habis oleh
                dokumen di luar scope, dan chunk yang sebenarnya layak di
                dokumen yang diminta tidak pernah masuk kandidat sama sekali.

        Returns:
            Pasangan ``(chunk_id, skor_bm25)``, urut menurun.
        """
        query_tokens = tokenize(query)
        if not query_tokens or not self.doc_freqs:
            return []

        total_documents = len(self.doc_freqs)
        average_length = self.average_length or 1.0
        k1, b = 1.5, 0.75

        scores: dict[str, float] = defaultdict(float)
        for token in set(query_tokens):
            matching = self.postings.get(token)
            if not matching:
                continue
            # IDF dengan variasi Robertson: token yang muncul di semua dokumen
            # mendapat IDF mendekati nol, yang benar karena memang tidak
            # informatif.
            document_frequency = len(matching)
            idf = math.log(
                1
                + (total_documents - document_frequency + 0.5)
                / (document_frequency + 0.5)
            )
            for identifier in matching:
                if allowed_ids is not None and identifier not in allowed_ids:
                    continue
                frequency = self.doc_freqs[identifier].get(token, 0)
                if frequency == 0:
                    continue
                length = self.doc_lengths[identifier]
                denominator = frequency + k1 * (1 - b + b * length / average_length)
                scores[identifier] += idf * (frequency * (k1 + 1)) / denominator

        ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
        return ranked[:top_k]


def reciprocal_rank_fusion(
    ranked_lists: Sequence[tuple[Sequence[str], float]],
    k: int = RRF_K,
) -> dict[str, float]:
    """Gabungkan beberapa daftar peringkat jadi satu skor.

    Args:
        ranked_lists: Satu tuple ``(ids_terurut, bobot)`` per sumber peringkat.
        k: Konstanta peredam. Nilai standar 60.

    Returns:
        Skor RRF per id, sudah dinormalisasi ke rentang 0..1.
    """
    fused: dict[str, float] = defaultdict(float)
    for identifiers, weight in ranked_lists:
        for rank, identifier in enumerate(identifiers):
            fused[identifier] += weight / (k + rank + 1)

    if not fused:
        return {}
    # RRF mentahnya kecil sekali, jadi diskalakan ke rentang 0..1 supaya bisa
    # ditampilkan di Citation Card.
    #
    # Penting: skor hasil normalisasi ini **tidak boleh dipakai untuk ambang
    # kelayakan**. Karena dibagi dengan nilai tertinggi, hasil terbaik selalu
    # tepat 1.0, sehingga ambang berapa pun di bawah 1.0 tidak pernah menolak
    # apa pun. Ambang diterapkan di ``HybridRetriever.retrieve`` pada bukti
    # mentah, bukan pada hasil fusi ini.
    best = max(fused.values())
    return {identifier: score / best for identifier, score in fused.items() if best > 0}


#: Konstanta saturasi penskalaan skor BM25 ke rentang 0..1.
#:
#: Nilainya menentukan **seberapa besar bukti leksikal harusnya** agar lolos
#: ambang. Dengan `s/(s+k)` dan ambang 0.5, bukti harus melebihi `k`. Versi
#: lama memakai k=12, yang berarti skor BM25 harus di atas 12, nilai yang
#: jarang terjadi pada dokumen pendek. Akibatnya jalur leksikal praktis mati:
#: retrieval hybrid claims bisa menaikkan recall untuk nomor klausul (yang
#: tidak pernah mirip secara vektor), tapi nyatanya tidak pernah dipakai.
#:
#: k=4 memberi jalur leksikal ruang bernapas tanpa mengubah urutan peringkat
#: (fungsi ini monoton, jadi peringkat tetap sama).
BM25_SATURATION = 4.0


def _normalized_keyword(score: float) -> float:
    """Skala skor BM25 ke rentang 0..1 dengan fungsi saturasi.

    Fungsi ``s / (s + k)`` dipilih karena punya dua sifat yang dibutuhkan:
    monoton (skor lebih besar tetap lebih besar, jadi peringkat tidak
    berubah) dan mendekati 1 tanpa pernah menyentuhnya, jadi tidak ada chunk
    yang salah dianggap "sangat relevan" hanya karena satu kata kunci
    muncul banyak kali.
    """
    if score <= 0:
        return 0.0
    return score / (score + BM25_SATURATION)


@dataclass(slots=True)
class IndexEntry:
    """Satu chunk yang sudah masuk indeks, lengkap dengan metadata-nya.

    Metadata disimpan di sini, bukan hanya di vector store, karena BM25 bisa
    menemukan chunk yang vektornya tidak pernah sampai ke kandidat (misalnya
    dokumen baru diindeks ulang). Tanpa metadata lokal, hit seperti itu akan
    dibuang dan retrieval berhenti jadi benar-benar hybrid.
    """

    chunk_id: str
    document_id: str
    document_name: str
    content: str
    chunk_index: int
    page_number: int | None


class HybridRetriever:
    """Pencari hybrid yang menggabungkan vektor dan BM25."""

    def __init__(
        self,
        store: VectorStore,
        reranker: Reranker | None = None,
        rerank_candidates: int = 8,
    ) -> None:
        self._store = store
        self._keyword_index = KeywordIndex()
        self._entries: dict[str, IndexEntry] = {}
        # Opsional, supaya test dan pemanggil lama tidak perlu tahu soal
        # reranking. Kalau None, perilakunya sama seperti sebelumnya.
        self._reranker = reranker
        # Kedalaman pool kandidat sebelum ambang. Sebelumnya setting ini
        # terbaca dari konfigurasi tapi tidak pernah dipakai; sekarang nilai
        # minimum pool kandidat yang diambil dari kedua sumber.
        self._rerank_candidates = max(1, rerank_candidates)

    @property
    def store_name(self) -> str:
        return self._store.name

    def index(self, entries: Iterable[IndexEntry]) -> None:
        """Bangun indeks kata dan simpan metadata setiap chunk."""
        for entry in entries:
            self._entries[entry.chunk_id] = entry
            self._keyword_index.add(entry.chunk_id, entry.content)

    def rebuild(self, entries: Iterable[IndexEntry]) -> int:
        """Bangun ulang seluruh indeks dari sumber kebenaran, lalu kembalikan jumlah chunk.

        Ini **wajib** dipanggil saat startup, bukan hanya saat ingestion.

        Tanpa itu, indeks kata dan peta metadata kosong setiap kali proses
        dimulai ulang, padahal dokumennya masih ada di SQLite dan Chroma.
        Gejalanya: retrieval mengembalikan daftar kosong, sehingga **setiap
        pertanyaan dijawab "tidak ditemukan"**, tidak ada error, tidak ada
        log, hanya perilaku yang masuk akal tapi salah total.

        Di localhost bug ini tidak terlihat karena dokumen baru saja di-upload
        saat indeksnya memang terisi. Ia baru muncul setelah deploy
        sungguhan, saat kontainer di-restart.

        Sumber kebenaran adalah metadata yang tersimpan, bukan vector store.
        Rebuild bersifat penuh karena yang tersedia adalah indeks kosong, jadi
        tidak ada yang perlu dipertahankan.
        """
        self.clear()
        collected = list(entries)
        self.index(collected)
        return len(collected)

    def clear(self) -> None:
        """Kosongkan seluruh indeks. Dipakai test dan reset penuh."""
        self._keyword_index = KeywordIndex()
        self._entries = {}

    def remove_document(self, document_id: str) -> int:
        """Buang semua chunk milik satu dokumen dari indeks kata.

        Dipakai saat dokumen dihapus. Kalau tidak, BM25 masih akan
        mengembalikan chunk dari dokumen yang sudah dihapus, dan dokumen lain
        ikut terpengaruh.

        Returns:
            Berapa banyak chunk yang dibuang.
        """
        doomed = [
            chunk_id
            for chunk_id, entry in self._entries.items()
            if entry.document_id == document_id
        ]
        for chunk_id in doomed:
            self._keyword_index.remove(chunk_id)
            self._entries.pop(chunk_id, None)
        return len(doomed)

    def _chunk_ids_for(self, document_ids: list[str] | None) -> set[str] | None:
        """Id chunk milik dokumen-dokumen tertentu, atau ``None`` untuk semua.

        Filter ini diterapkan sebelum RRF, bukan sesudahnya. Setelah fusi,
        kandidat yang luar scope baru dibuang, padahal mereka sudah
        memenuhi kuota kandidat dan menggeser peringkat chunk yang layak.
        """
        if not document_ids:
            return None
        wanted = set(document_ids)
        return {
            chunk_id
            for chunk_id, entry in self._entries.items()
            if entry.document_id in wanted
        }

    def retrieve(
        self,
        query: str,
        query_embedding: list[float],
        top_k: int,
        threshold: float,
        document_ids: Sequence[str] | None = None,
    ) -> list[RetrievedChunk]:
        """Ambil chunk yang relevan, sudah disaring ambang kelayakan.

        Args:
            query: Pertanyaan pengguna, dipakai untuk pencarian BM25.
            query_embedding: Vektor dari pertanyaan yang sama, dipakai untuk
                pencarian vektor.
            top_k: Berapa banyak chunk maksimum yang dikembalikan.
            threshold: Ambang kelayakan, diterapkan pada **bukti mentah**:
                cosine similarity vektor dan/atau skor BM25 yang sudah
                diskalakan. Tidak diterapkan pada skor RRF, karena skor itu
                dinormalisasi terhadap kandidat terbaik sehingga selalu ada
                satu bernilai 1.0. Kalau ambang dipasang di situ, ambang 0.7
                tidak akan pernah menolak apa pun, dan sistem akan menjawab
                dengan sumber yang tidak relevan.
            document_ids: Batasi hasil ke dokumen-dokumen ini saja. Kalau
                ``None``, pencarian memakai seluruh dokumen.

        Returns:
            Chunk yang layak, terurut dari paling relevan. List kosong berarti
            tidak ada yang cukup mirip, dan pemanggil harus menjawab "tidak
            ditemukan" daripada mengarang.
        """
        if not query.strip():
            return []

        filter_by: dict[str, object] | None = None
        if document_ids:
            filter_by = {"document_id": {"$in": list(document_ids)}}

        # Kandidat diambil lebih banyak dari top_k supaya RRF punya ruang
        # untuk kemudian memilih yang terbaik, dan supaya reranker punya
        # cukup kandidat untuk dinilai ulang (``rerank_candidates``).
        candidate_count = max(top_k * 4, self._rerank_candidates)
        vector_hits = self._store.query(
            embedding=query_embedding,
            collection=COLLECTION,
            top_k=candidate_count,
            where=filter_by,
        )
        keyword_hits = self._keyword_index.search(
            query,
            candidate_count,
            allowed_ids=self._chunk_ids_for(document_ids),
        )

        vector_ids = [identifier for identifier, _score, _meta in vector_hits]
        vector_scores = {identifier: score for identifier, score, _meta in vector_hits}
        keyword_ids = [identifier for identifier, _score in keyword_hits]
        keyword_scores = {identifier: score for identifier, score in keyword_hits}

        # RRF hanya untuk **peringkat**, bukan untuk kelayakan.
        fused = reciprocal_rank_fusion(
            [
                (vector_ids, VECTOR_WEIGHT),
                (keyword_ids, KEYWORD_WEIGHT),
            ]
        )

        # Metadata vektor lebih dipercayai karena berasal dari sumber yang sama
        # dengan vektornya. Metadata lokal hanya dipakai untuk chunk yang
        # benar-benar tidak ada di hasil vektor.
        metadata_by_id: dict[str, dict[str, object]] = {
            # Bukan C416: baris ini memfilter tuple tiga elemen menjadi
            # pasangan id -> metadata, bukan menyalin tuple apa adanya.
            identifier: metadata  # noqa: C416
            for identifier, _score, metadata in vector_hits  # noqa: C416
        }

        results: list[RetrievedChunk] = []
        # Batasi kontribusi satu dokumen. Tanpa batas ini, satu dokumen yang
        # chunk-nya banyak bisa memenuhi seluruh jatah `top_k`, dan jawaban
        # hanya melihat satu sumber padahal ada dokumen lain yang relevan,
        # pengguna melihat "8 sumber" yang sebenarnya dari satu berkas yang
        # sama.
        #
        # Tapi cap tidak boleh menyeseki scope satu dokumen: chat privat per
        # dokumen (kasus utama) hanya punya satu dokumen, dan cap 2 membuang
        # Pasal yang benar hanya karena ia kandidat ketiga. Jatah per dokumen
        # = pembagian rata top_k ke dokumen yang dicari, dengan lantai 2 untuk
        # kasus multi-dokumen.
        per_document_limit = (
            max(2, -(-top_k // len(document_ids)))
            if document_ids
            else max(2, top_k // 2)
        )
        per_document_count: dict[str, int] = {}

        for chunk_id, score in sorted(
            fused.items(), key=lambda item: item[1], reverse=True
        ):
            entry = self._entries.get(chunk_id)
            if entry is None:
                # Chunk tidak dikenal sama sekali: sudah dihapus, atau indeks
                # kata dan metadata lokal tidak sinkron. Lewati, jangan kirim
                # sumber yang tidak bisa diverifikasi.
                continue
            if document_ids and entry.document_id not in document_ids:
                continue
            if per_document_count.get(entry.document_id, 0) >= per_document_limit:
                continue

            vector_score = vector_scores.get(chunk_id, 0.0)
            keyword_score = keyword_scores.get(chunk_id, 0.0)

            # Ambang dinilai pada bukti mentah, bukan pada skor RRF. Skor RRF
            # dinormalisasi terhadap kandidat terbaik, jadi selalu ada satu
            # chunk bernilai 1.0 dan ambang di bawah 1.0 tidak akan pernah
            # menolak apa pun.
            #
            # Sebuah chunk layak kalau **salah satu** sumbernya cukup kuat:
            # relevan secara leksikal saja sudah layak (nomor klausul tidak
            # pernah mirip secara vektor), dan relevan secara semantik saja
            # juga layak (paragraf yang benar tapi tanpa kata kunci yang
            # sama). Menggabungkan dengan maksimum mempertahankan kedua jenis
            # kegunaan itu, yang justru alasan retrieval hybrid ada.
            strongest_evidence = max(
                vector_score, _normalized_keyword(keyword_score)
            )
            if strongest_evidence < threshold:
                continue

            metadata = metadata_by_id.get(chunk_id)
            per_document_count[entry.document_id] = (
                per_document_count.get(entry.document_id, 0) + 1
            )
            results.append(
                RetrievedChunk(
                    chunk=_chunk_for(chunk_id, entry, metadata),
                    # Nama dokumen mengikuti aturan yang sama dengan field lain:
                    # metadata vektor menang kalau ada, karena ditulis saat
                    # indexing dan bisa lebih baru kalau dokumen diunggah ulang
                    # dengan nama berbeda.
                    document_name=str(
                        (metadata or {}).get("document_name") or entry.document_name
                    ),
                    # Skor yang ditampilkan ke pengguna adalah fusi, karena
                    # itulah yang benar-benar menentukan peringkat akhir.
                    score=score,
                    vector_score=vector_score,
                    keyword_score=keyword_score,
                )
            )
            if len(results) >= top_k:
                break

        return self._rerank(query, results, top_k)

    def best_candidates(
        self,
        query: str,
        query_embedding: list[float],
        document_ids: Sequence[str] | None = None,
        limit: int = 3,
    ) -> list[RetrievedChunk]:
        """Kandidat terbaik **tanpa ambang**, untuk tier bukti lemah.

        ``retrieve`` menolak keras semua yang di bawah ambang, dan itu perilaku
        yang benar untuk anti-halusinasi. Tapi "tidak ada yang lolos ambang"
        bukan hal yang sama dengan "dokumen tidak membahasnya": sering ada
        kandidat yang benar-benar menyentuh topiknya hanya dengan skor lebih
        rendah. Method ini mengembalikan yang terbaik tanpa gerbang, supaya
        pemanggil bisa menawarkan jawaban berlabel bukti terbatas, bukan
        langsung menolak. Kandidat yang dikembalikan tetap perlu dinilai
        pemanggil (minimal lewat ``weak_evidence_floor``), bukan dipakai mentah.
        """
        if not query.strip() or limit <= 0:
            return []

        filter_by: dict[str, object] | None = None
        if document_ids:
            filter_by = {"document_id": {"$in": list(document_ids)}}

        candidate_count = max(self._rerank_candidates, limit * 4)
        vector_hits = self._store.query(
            embedding=query_embedding,
            collection=COLLECTION,
            top_k=candidate_count,
            where=filter_by,
        )
        keyword_hits = self._keyword_index.search(
            query,
            candidate_count,
            allowed_ids=self._chunk_ids_for(document_ids),
        )

        vector_scores = {identifier: score for identifier, score, _meta in vector_hits}
        keyword_scores = {identifier: score for identifier, score in keyword_hits}

        fused = reciprocal_rank_fusion(
            [
                ([identifier for identifier, _s, _m in vector_hits], VECTOR_WEIGHT),
                ([identifier for identifier, _s in keyword_hits], KEYWORD_WEIGHT),
            ]
        )

        metadata_by_id: dict[str, dict[str, object]] = {
            identifier: metadata  # noqa: C416
            for identifier, _score, metadata in vector_hits  # noqa: C416
        }

        # Tanpa ambang dan tanpa batas per dokumen: tujuannya memberi pemanggil
        # gambaran jujur atas apa yang paling dekat, bukan kandidat terkurasi.
        candidates: list[RetrievedChunk] = []
        for chunk_id, score in sorted(
            fused.items(), key=lambda item: item[1], reverse=True
        ):
            entry = self._entries.get(chunk_id)
            if entry is None:
                continue
            if document_ids and entry.document_id not in document_ids:
                continue
            candidates.append(
                RetrievedChunk(
                    chunk=_chunk_for(chunk_id, entry, metadata_by_id.get(chunk_id)),
                    document_name=str(
                        (metadata_by_id.get(chunk_id) or {}).get("document_name")
                        or entry.document_name
                    ),
                    score=score,
                    vector_score=vector_scores.get(chunk_id, 0.0),
                    keyword_score=keyword_scores.get(chunk_id, 0.0),
                )
            )
            if len(candidates) >= limit:
                break
        return candidates

    def _rerank(
        self, question: str, results: list[RetrievedChunk], top_k: int
    ) -> list[RetrievedChunk]:
        """Urutkan ulang hasil dengan cross-encoder, kalau diaktifkan.

        Dilakukan **setelah** ambang dan batas per dokumen diterapkan, bukan
        sebelum. Kalau reranking dijalankan lebih dulu, ia bisa mengangkat
        chunk yang sebenarnya di bawah ambang, dan itu membatalkan gerbang
        anti-halusinasi yang justru inti aplikasi ini. Reranking hanya boleh
        mengubah **urutan** kandidat yang sudah lolos, bukan menambah
        kandidat baru.

        ``top_k`` bisa mengecil setelah penyaringan ambang dan batas per
        dokumen. Yang diambil hanya sejumlah yang tersedia, supaya tidak ada
        pengisian paksa dengan chunk di bawah ambang hanya untuk memenuhi
        kuota.
        """
        if self._reranker is None or len(results) < 2:
            return results

        kandidat = [item.chunk.content for item in results]
        try:
            berperingkat = self._reranker.rerank(
                question, kandidat, min(top_k, len(kandidat))
            )
        except Exception:  # noqa: BLE001
            # Kegagalan reranker tidak boleh menggagalkan jawaban. Urutan
            # fusi tetap dipakai, karena itu sudah hasil yang sah.
            logger.warning(
                "Reranking gagal, memakai urutan fusi apa adanya.", exc_info=True
            )
            return results

        return [results[index] for index, _score in berperingkat]


def _chunk_for(
    chunk_id: str,
    entry: IndexEntry,
    metadata: dict[str, object] | None,
) -> Chunk:
    """Bangun objek Chunk dari metadata vektor, atau dari entri lokal.

    Metadata vektor lebih baru karena ditulis saat indexing, jadi dipakai
    duluan. Fallback ke entri lokal membuat chunk yang hanya dikenal BM25 tetap
    bisa ditampilkan lengkap dengan nomor halaman.
    """
    from app.models.domain import Chunk as _Chunk  # noqa: PLC0415

    if metadata:
        page = metadata.get("page_number")
        token_count = metadata.get("token_count")
        return _Chunk(
            id=chunk_id,
            document_id=str(metadata.get("document_id", entry.document_id)),
            chunk_index=int(metadata.get("chunk_index", entry.chunk_index)),
            content=str(metadata.get("content", entry.content)),
            page_number=(
                int(page) if isinstance(page, int | float) and page >= 0 else None
            ),
            token_count=(
                int(token_count) if isinstance(token_count, int | float) else None
            ),
        )

    return _Chunk(
        id=chunk_id,
        document_id=entry.document_id,
        chunk_index=entry.chunk_index,
        content=entry.content,
        page_number=entry.page_number,
    )
