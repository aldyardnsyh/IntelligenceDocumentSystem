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
import re
from collections import Counter, defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from app.models.domain import Chunk, RetrievedChunk
from app.services.retrieval.vector_store import VectorStore

logger = logging.getLogger(__name__)

COLLECTION = "chunks"

_TOKEN_RE = re.compile(r"[a-z0-9]+")

#: Bobot RRF. Vektor diberi bobot sedikit lebih tinggi karena lebih baik
#: menangkap maksud, sementara BM25 menangkap kelengkapan.
RRF_K = 60
VECTOR_WEIGHT = 1.0
KEYWORD_WEIGHT = 0.6

#: Kata kerja yang tidak membawa informasi dalam konteks dokumen ini.
_STOP_WORDS = frozenset(
    {
        "yang", "untuk", "dengan", "dari", "pada", "adalah", "akan", "atau",
        "dan", "itu", "ini", "apa", "bagaimana", "berapa", "di", "ke", "dalam",
        "oleh", "sebagai", "tersebut", "dapat", "harus", "sudah", "tidak",
        "juga", "bila", "kalau", "serta", "saya", "kami", "anda",
        "the", "a", "an", "of", "to", "is", "are", "in", "on", "for", "and",
        "or", "if", "be", "as", "at", "by", "it", "this", "that",
    }
)


def tokenize(text: str) -> list[str]:
    """Pecah teks menjadi token, buang stop word.

    Dua aturan pembuangan, dan alasannya berbeda:

    - **Stop word** dibuang karena tidak membawa makna apa pun dalam konteks
      dokumen ini.
    - **Token satu huruf** dibuang kalau berupa huruf, tapi **angka satu digit
      justru disimpan**. "pasal 2" dan "bagian 3" adalah rujukan yang sangat
      spesifik; membuang "2" membuat pencarian "pasal 2" tidak menemukan
      "pasal 2". Justru kasus inilah yang paling perlu ditangani, dan
      memfilter angka pendek akan merusaknya.

    Catatan penting: tidak ada daftar "kata generik" manual. Kata seperti
    "dokumen" atau "permintaan" memang tidak membedakan satu dokumen dari
    yang lain, tapi IDF milik BM25 sudah otomatis menurunkan kontribusinya
    karena kata itu muncul di hampir semua chunk. Memblokirnya secara manual
    hanya menggandakan pekerjaan IDF, dan lebih buruk lagi: kalau seluruh
    pertanyaan hanya comprised kata generik, semua token habis dan sistem
    menjawab "tidak ditemukan" padahal dokumennya ada.
    """
    tokens = _TOKEN_RE.findall(text.lower())
    return [
        token
        for token in tokens
        if (len(token) > 1 or token.isdigit()) and token not in _STOP_WORDS
    ]


@dataclass(slots=True)
class KeywordIndex:
    """Indeks BM25 sederhana di atas daftar chunk.

    Untuk portofolio dengan ribuan chunk, ini masih cukup. Kalau dokumennya
    tumbuh jadi ratusan ribu chunk, indeks ini perlu dipindah ke mesin
    pencarian khusus (Meilisearch, Elasticsearch), karena pembaruan in-memory
    jadi mahal.
    """

    document_ids: list[str] = None  # type: ignore[assignment]
    frequencies: list[Counter[str]] = None  # type: ignore[assignment]
    document_frequency: Counter[str] = None  # type: ignore[assignment]
    lengths: list[int] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.document_ids is None:
            self.document_ids = []
        if self.frequencies is None:
            self.frequencies = []
        if self.document_frequency is None:
            self.document_frequency = Counter()
        if self.lengths is None:
            self.lengths = []

    @property
    def average_length(self) -> float:
        if not self.lengths:
            return 0.0
        return sum(self.lengths) / len(self.lengths)

    def add(self, document_id: str, content: str) -> None:
        """Tambahkan satu chunk ke indeks kata.

        Kalau id-nya sudah ada, konten lama dikurangi dulu supaya
        ``document_frequency`` tidak ikut_naik dua kali untuk dokumen yang
        sama.
        """
        tokens = tokenize(content)
        frequency = Counter(tokens)
        if document_id in self.document_ids:
            # Pergantian konten: kurangi frekuensi dokumen lama dulu.
            self.remove(document_id)
        self.document_ids.append(document_id)
        self.frequencies.append(frequency)
        self.lengths.append(len(tokens))
        for token in frequency:
            self.document_frequency[token] += 1

    def remove(self, document_id: str) -> None:
        """Buang satu chunk dari indeks. Aman kalau id-nya tidak ada."""
        try:
            index = self.document_ids.index(document_id)
        except ValueError:
            return
        for token in self.frequencies[index]:
            self.document_frequency[token] -= 1
        self.document_ids.pop(index)
        self.frequencies.pop(index)
        self.lengths.pop(index)

    def search(
        self,
        query: str,
        top_k: int,
        allowed_ids: set[str] | None = None,
    ) -> list[tuple[str, float]]:
        """BM25 dengan parameter standar k1=1.5, b=0.75.

        Args:
            query: Pertanyaan pengguna, sudah di-tokenisasi oleh pemanggil
                (``tokenize`` dipanggil di sini).
            top_k: Berapa banyak hasil yang dikembalikan.
            allowed_ids: Batasi hanya id chunk milik dokumen yang diminta. Tanpa
                filter ini, kandidat yang mengisi ``top_k`` bisa habis oleh
                dokumen di luar scope, dan chunk yang sebenarnya layak di
                dokumen yang diminta tidak pernah masuk kandidat sama sekali.

        Returns:
            Pasangan ``(chunk_id, skor_bm25)``, urut menurun.
        """
        query_tokens = tokenize(query)
        if not query_tokens or not self.document_ids:
            return []

        total_documents = len(self.document_ids)
        average_length = self.average_length or 1.0
        k1, b = 1.5, 0.75

        scores: dict[str, float] = defaultdict(float)
        for token in set(query_tokens):
            document_frequency = self.document_frequency.get(token, 0)
            if document_frequency == 0:
                continue
            # IDF dengan variasi Robertson: token yang muncul di semua dokumen
            # mendapat IDF mendekati nol, yang benar karena memang tidak
            # informatif.
            idf = math.log(
                1
                + (total_documents - document_frequency + 0.5)
                / (document_frequency + 0.5)
            )
            for index, identifier in enumerate(self.document_ids):
                if allowed_ids is not None and identifier not in allowed_ids:
                    continue
                frequency = self.frequencies[index].get(token, 0)
                if frequency == 0:
                    continue
                length = self.lengths[index]
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

    def __init__(self, store: VectorStore) -> None:
        self._store = store
        self._keyword_index = KeywordIndex()
        self._entries: dict[str, IndexEntry] = {}

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
        # untuk kemudian memilih yang terbaik.
        candidate_count = max(top_k * 4, top_k)
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
        per_document_limit = max(2, top_k // 2)
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

        return results


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
