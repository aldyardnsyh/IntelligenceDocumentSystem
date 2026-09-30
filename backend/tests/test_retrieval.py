"""Test retrieval: cosine similarity, RRF, dan BM25."""

from __future__ import annotations

import math

import pytest

from app.services.retrieval.retriever import (
    HybridRetriever,
    IndexEntry,
    KeywordIndex,
    reciprocal_rank_fusion,
    tokenize,
)
from app.services.retrieval.vector_store import (
    InMemoryVectorStore,
    VectorRecord,
    cosine_similarity,
)
from tests.conftest import SAMPLE_DOCUMENT


def _entry(
    chunk_id: str,
    document_id: str,
    content: str,
    page_number: int | None,
    document_name: str = "panduan.md",
) -> IndexEntry:
    """Bantu construir ``IndexEntry`` supaya test fokus pada perilaku."""
    return IndexEntry(
        chunk_id=chunk_id,
        document_id=document_id,
        document_name=document_name,
        content=content,
        chunk_index=0,
        page_number=page_number,
    )


class TestCosineSimilarity:
    def test_vektor_identik_skor_satu(self) -> None:
        vector = [0.1, 0.2, 0.3]
        assert cosine_similarity(vector, vector) == pytest.approx(1.0)

    def test_vektor_berlawanan_skor_minus_satu(self) -> None:
        vector = [0.1, 0.2, 0.3]
        assert cosine_similarity(vector, [-value for value in vector]) == pytest.approx(-1.0)

    def test_vektor_tegak_lurus_skor_nol(self) -> None:
        assert cosine_similarity([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)

    def test_vektor_nol_skor_nol_bukan_error(self) -> None:
        # Vektor nol tidak punya arah, jadi similarity-nya tidak terdefinisi.
        # Mengembalikan 0 lebih aman daripada melempar exception.
        assert cosine_similarity([0.0, 0.0], [1.0, 1.0]) == 0.0

    def test_menolak_dimensi_berbeda(self) -> None:
        with pytest.raises(ValueError, match="Dimensi"):
            cosine_similarity([1.0, 2.0], [1.0, 2.0, 3.0])

    def test_nilai_selalu_dalam_rentang_kosinus(self) -> None:
        left = [0.3, 0.4, 0.5, 0.6]
        right = [0.6, 0.5, 0.4, 0.3]
        assert -1.0 <= cosine_similarity(left, right) <= 1.0


class TestTokenize:
    def test_membuang_stop_word(self) -> None:
        tokens = tokenize("Yang ini adalah sebuah dokumen")
        assert "yang" not in tokens
        assert "dokumen" in tokens

    def test_membuang_tanda_baca_dan_menurunkan_kapital(self) -> None:
        assert tokenize("Klausul, 14.2!") == ["klausul", "14", "2"]

    def test_membuang_token_satu_huruf(self) -> None:
        assert tokenize("a b kata") == ["kata"]

    def test_menghasilkan_daftar_kosong_untuk_kalimat_masih(self) -> None:
        assert tokenize("yang dan atau dengan") == []


class TestReciprocalRankFusion:
    def test_gabungan_kosong_memberi_hasil_kosong(self) -> None:
        assert reciprocal_rank_fusion([]) == {}

    def test_daftar_tunggal_masih_dinormalisasi(self) -> None:
        fused = reciprocal_rank_fusion([(["a", "b", "c"], 1.0)])
        # Peringkat pertama harus bernilai paling tinggi dan selalu 1.0.
        assert max(fused.values()) == pytest.approx(1.0)
        assert fused["a"] > fused["b"] > fused["c"]

    def test_sumber_yang_sepakat_dapat_boost(self) -> None:
        # "a" peringkat 1 di vektor dan peringkat 1 di kata kunci, jadi harus
        # menang telak dibanding yang hanya muncul di satu sumber.
        fused = reciprocal_rank_fusion([(["a", "b"], 1.0), (["a", "c"], 0.6)])
        assert fused["a"] > fused["b"]
        assert fused["a"] > fused["c"]

    def test_hasil_selalu_dalam_rentang_nol_sampai_satu(self) -> None:
        fused = reciprocal_rank_fusion([(["a", "b"], 1.0), (["b", "c"], 0.6)])
        assert all(0.0 <= value <= 1.0 for value in fused.values())


class TestKeywordIndex:
    def test_pencarian_kata_kunci_mencocokkan(self) -> None:
        index = KeywordIndex()
        index.add("c1", "batas waktu penyelesaian adalah dua hari kerja")
        index.add("c2", "permintaan informasi harus diverifikasi lengkap")
        results = index.search("penyelesaian dua hari", top_k=5)
        assert results
        assert results[0][0] == "c1"

    def test_tidak_ada_kecocokan_memberi_daftar_kosong(self) -> None:
        index = KeywordIndex()
        index.add("c1", "isi dokumen")
        assert index.search("katayangtidakada", top_k=5) == []

    def test_indeks_kosong_aman_dipakai(self) -> None:
        assert KeywordIndex().search("apa saja", top_k=5) == []

    def test_menambahkan_ulang_id_mengganti_konten(self) -> None:
        index = KeywordIndex()
        index.add("c1", "konten awal dengan kata alphaword")
        index.add("c1", "konten baru dengan kata bravo")
        results = index.search("alphaword", top_k=5)
        # Kata lama harus hilang, karena kontennya sudah diganti.
        assert not any(identifier == "c1" for identifier, _ in results)
        assert index.document_ids.count("c1") == 1

    def test_remove_mengurangi_frekuensi_dokumen(self) -> None:
        index = KeywordIndex()
        index.add("c1", "kata unik di sini")
        index.add("c2", "kata unik di situ")
        before = index.document_frequency["unik"]
        index.remove("c1")
        assert index.document_frequency["unik"] == before - 1

    def test_remove_id_tidak_ada_aman(self) -> None:
        index = KeywordIndex()
        index.remove("tidak-ada")  # tidak boleh melempar

    def test_panjang_rata_rata_benar(self) -> None:
        index = KeywordIndex()
        index.add("c1", "satu dua")
        index.add("c2", "satu dua tiga empat")
        assert index.average_length == pytest.approx(3.0)


class TestHybridRetriever:
    def test_tidak_ada_dokumen_memberi_hasil_kosong(self, store: InMemoryVectorStore) -> None:
        retriever = HybridRetriever(store)
        assert retriever.retrieve("apa saja", [0.1, 0.2, 0.3], 5, 0.1) == []

    def test_pertanyaan_kosong_tidak_mencari(self, store: InMemoryVectorStore) -> None:
        retriever = HybridRetriever(store)
        assert retriever.retrieve("   ", [0.1, 0.2, 0.3], 5, 0.0) == []

    def test_ambang_tinggi_menolak_semua(
        self, store: InMemoryVectorStore, embedding, retriever: HybridRetriever
    ) -> None:
        store.upsert(
            [
                VectorRecord(
                    id="c1",
                    embedding=embedding.embed_query(SAMPLE_DOCUMENT[:400]),
                    metadata={
                        "document_id": "d1",
                        "document_name": "panduan.md",
                        "chunk_index": 0,
                        "page_number": 1,
                        "content": SAMPLE_DOCUMENT[:400],
                        "token_count": 100,
                    },
                )
            ],
            "chunks",
        )
        retriever.index([_entry("c1", "d1", SAMPLE_DOCUMENT[:400], 1)])
        # Ambang di atas 1 mustahil dicapai karena skor dinormalisasi ke 0..1.
        assert retriever.retrieve("penyelesaian", [0.1, 0.2, 0.3], 5, 1.1) == []

    def test_ambang_nol_mengambil_kandidat(
        self, store: InMemoryVectorStore, embedding, retriever: HybridRetriever
    ) -> None:
        text = "batas waktu penyelesaian adalah dua hari kerja"
        store.upsert(
            [
                VectorRecord(
                    id="c1",
                    embedding=embedding.embed_query(text),
                    metadata={
                        "document_id": "d1",
                        "document_name": "panduan.md",
                        "chunk_index": 0,
                        "page_number": 1,
                        "content": text,
                        "token_count": 10,
                    },
                )
            ],
            "chunks",
        )
        retriever.index([_entry("c1", "d1", text, 1)])
        results = retriever.retrieve("penyelesaian", embedding.embed_query(text), 5, 0.0)
        assert results
        assert results[0].chunk.id == "c1"
        assert results[0].document_name == "panduan.md"

    def test_filter_document_id_membatasi_hasil(
        self, store: InMemoryVectorStore, embedding, retriever: HybridRetriever
    ) -> None:
        text = "isi yang sama persis untuk dua dokumen berbeda"
        store.upsert(
            [
                VectorRecord(
                    id="c1",
                    embedding=embedding.embed_query(text),
                    metadata={
                        "document_id": "d1",
                        "document_name": "satu.md",
                        "chunk_index": 0,
                        "page_number": None,
                        "content": text,
                        "token_count": 10,
                    },
                ),
                VectorRecord(
                    id="c2",
                    embedding=embedding.embed_query(text),
                    metadata={
                        "document_id": "d2",
                        "document_name": "dua.md",
                        "chunk_index": 0,
                        "page_number": None,
                        "content": text,
                        "token_count": 10,
                    },
                ),
            ],
            "chunks",
        )
        retriever.index([_entry("c1", "d1", text, None), _entry("c2", "d2", text, None, "dua.md")])
        results = retriever.retrieve(
            "isi", embedding.embed_query(text), 5, 0.0, document_ids=["d2"]
        )
        assert results
        assert all(item.chunk.document_id == "d2" for item in results)

    def test_top_k_membatasi_jumlah_hasil(
        self, store: InMemoryVectorStore, embedding, retriever: HybridRetriever
    ) -> None:
        base = "penyelesaian dua hari kerja"
        records = []
        index_entries = []
        for index in range(8):
            text = f"{base} varian nomor {index}"
            identifier = f"c{index}"
            records.append(
                VectorRecord(
                    id=identifier,
                    embedding=embedding.embed_query(text),
                    metadata={
                        "document_id": "d1",
                        "document_name": "panduan.md",
                        "chunk_index": index,
                        "page_number": None,
                        "content": text,
                        "token_count": 10,
                    },
                )
            )
            index_entries.append(_entry(identifier, "d1", text, None))
        store.upsert(records, "chunks")
        retriever.index(index_entries)
        results = retriever.retrieve(base, embedding.embed_query(base), 3, 0.0)
        assert len(results) == 3

    def test_clear_mengosongkan_indeks_kata(self, store: InMemoryVectorStore) -> None:
        retriever = HybridRetriever(store)
        retriever.index([_entry("c1", "d1", "isi", None)])
        retriever.clear()
        # Setelah clear, pencarian hanya bersandar pada vektor.
        assert retriever._keyword_index.document_ids == []

    def test_vektor_dimensi_berbeda_dilewati_bukan_gagal(self, store: InMemoryVectorStore) -> None:
        retriever = HybridRetriever(store)
        store.upsert(
            [
                VectorRecord(
                    id="c1",
                    embedding=[0.1, 0.2],
                    metadata={
                        "document_id": "d1",
                        "document_name": "x",
                        "chunk_index": 0,
                        "page_number": None,
                        "content": "teks",
                        "token_count": 1,
                    },
                )
            ],
            "chunks",
        )
        # Query dengan dimensi berbeda harus dilewati, bukan melempar error
        # yang membatalkan seluruh pencarian.
        results = retriever.retrieve("teks", [0.1] * 384, 5, 0.0)
        assert results == []


class TestVectorStore:
    def test_upsert_lalu_query_mengembalikan_metadata(self) -> None:
        store = InMemoryVectorStore()
        store.upsert(
            [VectorRecord(id="c1", embedding=[1.0, 0.0], metadata={"document_id": "d1"})],
            "koleksi",
        )
        results = store.query([1.0, 0.0], "koleksi", top_k=5)
        assert results[0][0] == "c1"
        assert results[0][2]["document_id"] == "d1"

    def test_query_koleksi_kosong(self) -> None:
        assert InMemoryVectorStore().query([1.0], "tidak-ada", 5) == []

    def test_upsert_mengganti_record_yang_sama(self) -> None:
        store = InMemoryVectorStore()
        store.upsert([VectorRecord(id="c1", embedding=[1.0, 0.0], metadata={})], "k")
        store.upsert([VectorRecord(id="c1", embedding=[0.0, 1.0], metadata={})], "k")
        assert store.count("k") == 1
        results = store.query([0.0, 1.0], "k", 1)
        assert results[0][1] == pytest.approx(1.0)

    def test_delete_collection_menghapus_semua(self) -> None:
        store = InMemoryVectorStore()
        store.upsert([VectorRecord(id="c1", embedding=[1.0], metadata={})], "k")
        store.delete_collection("k")
        assert store.count("k") == 0

    def test_filter_metadata_bekerja(self) -> None:
        store = InMemoryVectorStore()
        store.upsert(
            [
                VectorRecord(id="c1", embedding=[1.0, 0.0], metadata={"document_id": "d1"}),
                VectorRecord(id="c2", embedding=[1.0, 0.0], metadata={"document_id": "d2"}),
            ],
            "k",
        )
        results = store.query([1.0, 0.0], "k", 5, where={"document_id": "d2"})
        assert [item[0] for item in results] == ["c2"]

    def test_operator_in_pada_filter(self) -> None:
        store = InMemoryVectorStore()
        store.upsert(
            [
                VectorRecord(id="c1", embedding=[1.0], metadata={"document_id": "d1"}),
                VectorRecord(id="c2", embedding=[1.0], metadata={"document_id": "d2"}),
            ],
            "k",
        )
        results = store.query([1.0], "k", 5, where={"document_id": {"$in": ["d1", "d2"]}})
        assert len(results) == 2


class TestRebuildSetelahRestart:
    """Regression test untuk bug yang hanya muncul setelah deploy.

    Indeks BM25 dan peta metadata dulu hanya terisi oleh dokumen yang
    diunggah selama proses berjalan. Setelah container di-restart, dokumennya
    masih ada di vector store dan database, tapi retriever tidak tahu apa pun
    -- sehingga setiap pertanyaan dijawab "tidak ditemukan" tanpa error.

    Bug ini mustahil terlihat di localhost, karena di sana dokumen baru saja
    di-upload. Ia baru muncul ketika proses dimulai ulang.
    """

    def test_rebuild_mengembalikan_chunk_yang_tersimpan(
        self, store: InMemoryVectorStore, embedding
    ) -> None:
        from app.services.retrieval.retriever import HybridRetriever

        text = "batas waktu penyelesaian adalah dua hari kerja"

        # Simulasikan kondisi setelah restart: dokumen sudah ada di
        # penyimpanan, tapi indeks retriever masih kosong.
        store.upsert(
            [
                VectorRecord(
                    id="c1",
                    embedding=embedding.embed_query(text),
                    metadata={
                        "document_id": "d1",
                        "document_name": "panduan.md",
                        "chunk_index": 0,
                        "page_number": 1,
                        "content": text,
                        "token_count": 10,
                    },
                )
            ],
            "chunks",
        )
        retriever = HybridRetriever(store)

        # Sebelum rebuild: tidak ada yang bisa ditemukan meski dokumen ada.
        assert retriever.retrieve("penyelesaian", embedding.embed_query(text), 5, 0.0) == []

        restored = retriever.rebuild(
            [_entry("c1", "d1", text, 1, document_name="panduan.md")]
        )
        assert restored == 1

        # Setelah rebuild: dokumen bisa ditemukan lagi.
        results = retriever.retrieve("penyelesaian", embedding.embed_query(text), 5, 0.0)
        assert [item.chunk.id for item in results] == ["c1"]
        assert results[0].document_name == "panduan.md"
        assert results[0].chunk.page_number == 1

    def test_rebuild_kosong_tidak_melempar(self) -> None:
        from app.services.retrieval.retriever import HybridRetriever

        # Corpus kosong adalah kondisi normal untuk instalasi baru, bukan error.
        assert HybridRetriever(InMemoryVectorStore()).rebuild([]) == 0

    def test_rebuild_mengganti_indeks_sebelumnya(
        self, store: InMemoryVectorStore, embedding
    ) -> None:
        """Rebuild harus penuh, bukan menumpuk di atas data lama.

        Kalau tidak, chunk dari dokumen yang sudah dihapus akan tetap bisa
        dicari setelah restart.
        """
        from app.services.retrieval.retriever import HybridRetriever

        retriever = HybridRetriever(store)
        retriever.rebuild([_entry("lama", "d1", "dokumen lama yang sudah dihapus", 1)])
        retriever.rebuild([_entry("baru", "d2", "dokumen baru", 1)])

        assert set(retriever._entries) == {"baru"}

    def test_indeks_kata_ikut_terisi_setelah_rebuild(self) -> None:
        from app.services.retrieval.retriever import HybridRetriever

        retriever = HybridRetriever(InMemoryVectorStore())
        retriever.rebuild(
            [_entry("c1", "d1", "pasal 12 ayat 3 tentang penundaan pembayaran", 1)]
        )
        # BM25 harus bisa menjangkau chunk-nya, bukan cuma vektor.
        assert retriever._keyword_index.search("pasal 12", 5)


class TestHibridSesungguhnyaHibrid:
    """Regression test untuk hit yang hanya ditemukan BM25.

    Versi sebelumnya mengambil metadata hanya dari hasil vektor, lalu
    membuang hit BM25 yang tidak ada di sana. Hasilnya: dokumen dengan
    kata kunci spesifik seperti nomor klausul tidak pernah bisa ditemukan,
    dan sistem yang diklaim hybrid sebenarnya hanya semi-hybrid.
    """

    def test_hit_keyword_tanpa_vektor_tidak_buang(self) -> None:
        retriever = HybridRetriever(InMemoryVectorStore())
        # Tidak ada satu pun vektor di store; hanya indeks kata yang terisi.
        retriever.index([_entry("c1", "d1", "pasal 12 ayat 3 tentang penundaan", 1)])

        results = retriever.retrieve("pasal 12", [0.0] * 384, 5, 0.0)
        assert results
        assert results[0].chunk.id == "c1"
        # Sitasi harus lengkap walau metadata vektor tidak ada.
        assert results[0].chunk.content
        assert results[0].chunk.page_number == 1
        assert results[0].document_name == "panduan.md"

    def test_nama_dokumen_dari_entri_lokal(self) -> None:
        retriever = HybridRetriever(InMemoryVectorStore())
        retriever.index([_entry("c1", "d1", "isi", None, document_name="kontrak.pdf")])
        results = retriever.retrieve("isi", [0.0] * 384, 5, 0.0)
        assert results[0].document_name == "kontrak.pdf"

    def test_metadata_vektor_mengalahkan_metadata_lokal(self) -> None:
        store = InMemoryVectorStore()
        text = "batas waktu penyelesaian dua hari kerja"
        store.upsert(
            [
                VectorRecord(
                    id="c1",
                    embedding=[1.0, 0.0],
                    metadata={
                        "document_id": "d1",
                        "document_name": "nama-dari-vektor.pdf",
                        "chunk_index": 7,
                        "page_number": 4,
                        "content": text,
                        "token_count": 12,
                    },
                )
            ],
            "chunks",
        )
        retriever = HybridRetriever(store)
        retriever.index([_entry("c1", "d1", text, 1, document_name="nama-lama.md")])

        results = retriever.retrieve("penyelesaian", [1.0, 0.0], 5, 0.0)
        # Metadata vektor ditulis saat indexing dan lebih baru, jadi menang.
        assert results[0].chunk.chunk_index == 7
        assert results[0].chunk.page_number == 4
        assert results[0].document_name == "nama-dari-vektor.pdf"

    def test_chunk_diindeks_tetapi_bukan_dari_vector_tidak_masuk(self) -> None:
        """Entri yang sudah dihapus tidak boleh muncul sebagai sitasi.

        Kalau entri lokal dan indeks kata tidak dibersihkan, chunk dari
        dokumen yang sudah dihapus akan muncul sebagai sumber yang tidak
        bisa diklik.
        """
        retriever = HybridRetriever(InMemoryVectorStore())
        retriever.index([_entry("c1", "d1", "isi lama", 1)])
        retriever.remove_document("d1")
        assert retriever.retrieve("isi", [0.0] * 384, 5, 0.0) == []


class TestRemoveDocument:
    def test_menghapus_semua_chunk_satu_dokumen(self) -> None:
        retriever = HybridRetriever(InMemoryVectorStore())
        retriever.index(
            [
                _entry("c1", "d1", "isi dokumen satu", 1),
                _entry("c2", "d1", "isi dokumen satu lagi", 2),
                _entry("c3", "d2", "isi dokumen dua", 1),
            ]
        )
        removed = retriever.remove_document("d1")
        assert removed == 2

        # Dokumen dua harus tetap bisa dicari.
        results = retriever.retrieve("dokumen dua", [0.0] * 384, 5, 0.0)
        assert [item.chunk.id for item in results] == ["c3"]

    def test_dokumen_lain_tidak_ikut_terhapus(self) -> None:
        """Regression: menghapus satu dokumen tidak boleh mengosongkan indeks.

        ``delete_collection`` yang dipakai versi sebelumnya menghapus seluruh
        koleksi vektor sekaligus, jadi satu penghapusan merusak semua dokumen
        lain tanpa ada pesan error apa pun. Lapisan ini hanya membersihkan
        indeks kata; penghapusan vektor ditangani ``store.delete_document``.
        """
        store = InMemoryVectorStore()
        store.upsert(
            [
                VectorRecord(
                    id="c1",
                    embedding=[1.0, 0.0],
                    metadata={"document_id": "d1", "content": "satu"},
                ),
                VectorRecord(
                    id="c2",
                    embedding=[1.0, 0.0],
                    metadata={"document_id": "d2", "content": "dua"},
                ),
            ],
            "chunks",
        )
        retriever = HybridRetriever(store)
        retriever.index(
            [_entry("c1", "d1", "satu", 1), _entry("c2", "d2", "dua", 1)]
        )

        retriever.remove_document("d1")
        # Yang tersisa harus hanya dokumen dua, dari kedua lapisannya.
        assert [item.chunk.id for item in retriever.retrieve("dua", [0.0] * 384, 5, 0.0)] == ["c2"]
        store.delete_document("d1", "chunks")
        assert [item[0] for item in store.query([1.0, 0.0], "chunks", 5)] == ["c2"]

    def test_hapus_dokumen_tidak_ada_aman(self) -> None:
        retriever = HybridRetriever(InMemoryVectorStore())
        assert retriever.remove_document("tidak-ada") == 0


class TestDeleteDocumentVectorStore:
    def test_hanya_menghapus_dokumen_yang_diminta(self) -> None:
        store = InMemoryVectorStore()
        store.upsert(
            [
                VectorRecord(id="c1", embedding=[1.0], metadata={"document_id": "d1"}),
                VectorRecord(id="c2", embedding=[1.0], metadata={"document_id": "d1"}),
                VectorRecord(id="c3", embedding=[1.0], metadata={"document_id": "d2"}),
            ],
            "k",
        )
        removed = store.delete_document("d1", "k")
        assert removed == 2
        assert store.count("k") == 1
        assert store.query([1.0], "k", 5)[0][0] == "c3"

    def test_hapus_dokumen_tidak_ada_mengembalikan_nol(self) -> None:
        store = InMemoryVectorStore()
        store.upsert([VectorRecord(id="c1", embedding=[1.0], metadata={"document_id": "d1"})], "k")
        assert store.delete_document("tidak-ada", "k") == 0
        assert store.count("k") == 1

    def test_ping_selalu_true_untuk_in_memory(self) -> None:
        assert InMemoryVectorStore().ping() is True


def test_cosine_vector_nilai_ekstrem_tidak_menghasilkan_nan() -> None:
    """Nilai ekstrem tidak boleh menghasilkan NaN yang merusak sorting."""
    left = [1e-9, -1e-9, 1e-9]
    right = [1e9, -1e9, 1e9]
    result = cosine_similarity(left, right)
    assert not math.isnan(result)
