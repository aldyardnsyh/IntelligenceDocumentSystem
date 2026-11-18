"""Kualitas korpus & gate bukti.

Mengunci perilaku yang mencegah teks ekstraksi kotor dipakai diam-diam:
pembersihan simbol/hyphen/fusion ber-digit, penilaian kualitas per chunk
(flag-only), gate bukti dua bar (semantik vs leksikal murni), toleransi typo
dan padanan kata di BM25, serta penanda sumber meragukan di prompt.
"""

from __future__ import annotations

import pytest

from app.models.domain import Chunk, RetrievedChunk
from app.services.generation.prompts import (
    SYSTEM_PROMPT,
    WEAK_EVIDENCE_SYSTEM_PROMPT,
    build_context_prompt,
)
from app.services.ingestion.chunker import TextSpan
from app.services.ingestion.cleanup import (
    clean_page_text,
    join_broken_words,
    normalize_symbols,
    split_fused_words,
)
from app.services.ingestion.service import IngestionService
from app.services.ingestion.text_quality import (
    CHUNK_FLAG_LOW,
    CHUNK_FLAG_OK,
    assess_chunk_quality,
)
from app.services.retrieval.retriever import (
    HybridRetriever,
    IndexEntry,
    KeywordIndex,
    _normalized_keyword,
)
from app.services.retrieval.text_processing import (
    configure_stemming,
    normalize_query,
)
from app.services.retrieval.vector_store import InMemoryVectorStore, VectorRecord

# --------------------------------------------------------------------------
# Paket 1: pembersihan teks.
# --------------------------------------------------------------------------


class TestNormalizeSymbols:
    def test_kutipan_keriting_jadi_ascii(self) -> None:
        assert normalize_symbols("\u2018baca\u2019 \u201cPasal 5\u201d") == "'baca' \"Pasal 5\""

    def test_dash_panjang_jadi_hyphen(self) -> None:
        assert normalize_symbols("kesatu\u2013kedua\u2014tiga\u2026selesai") == (
            "kesatu-kedua-tiga...selesai"
        )

    def test_isi_kata_tidak_disentuh(self) -> None:
        # Normalisasi hanya menyentuh tanda baca; kata apapun harus utuh.
        assert normalize_symbols("penyelenggaraan pengaduan") == (
            "penyelenggaraan pengaduan"
        )

    def test_teks_kosong_aman(self) -> None:
        assert normalize_symbols("") == ""


class TestJoinBrokenWords:
    def test_kata_terpotong_akhir_baris_tersambung(self) -> None:
        assert join_broken_words("pemerin-\ntahan") == "pemerintahan"

    def test_hyphen_tengah_baris_tetap_ada(self) -> None:
        # Tanda hubung sah di tengah baris ("sosiologis-politis") tidak boleh
        # ikut hilang.
        assert join_broken_words("kajian sosiologis-politis") == (
            "kajian sosiologis-politis"
        )

    def test_hyphen_di_awal_baris_tidak_tersambung(self) -> None:
        # Pola butir "(a)-" atau baris berawalan hyfen bukan pecahan kata.
        text = "Pasal 2\n- 12 -"
        assert join_broken_words(text) == text


class TestFusionDigit:
    def test_fusion_kata_dan_angka_terpecah(self) -> None:
        # Token minimal 18 karakter (ambang fusion); di bawah itu dibiarkan.
        assert split_fused_words("BagianTahun2008Nomor38") == (
            "Bagian Tahun 2008 Nomor 38"
        )

    def test_fusion_pendek_dibiarkan_apa_adanya(self) -> None:
        # Di bawah ambang 18 karakter, kata sah yang mengandung angka tidak
        # diutak-atik — konservatif lebih baik daripada salah potong.
        assert split_fused_words("Tahun2008Nomor38") == "Tahun2008Nomor38"

    def test_angka_murni_tidak_disentuh(self) -> None:
        assert split_fused_words("Nomor 2008 Pasal 12") == "Nomor 2008 Pasal 12"

    def test_angka_tidak_terpecah_per_digit(self) -> None:
        # Regresi: DP lama memenangkan "2 0 0 8" karena tiebreak banyak kata.
        assert split_fused_words("Nomor38Tahun2009TentangPengelolaan") == (
            "Nomor 38 Tahun 2009 Tentang Pengelolaan"
        )

    def test_fusion_dengan_angka_di_awal_tetap_am(self) -> None:
        # Diawali digit: bukan pola fusion kata; angka sah tidak dipotong.
        assert split_fused_words("2008Tahun") == "2008Tahun"

    def test_kata_sah_kapital_di_awal_baris_dikenali(self) -> None:
        assert split_fused_words("PengaduanKeluhanPelayananPublik") == (
            "Pengaduan Keluhan Pelayanan Publik"
        )

    def test_nama_lembaga_tak_kenal_tetap_utuh(self) -> None:
        # "Direktoral..." tidak ada di kamus; lebih aman utuh daripada
        # terbelah "Di rektoral..." oleh tiebreak.
        hasil = split_fused_words("DirektoralJenderalAdministrasiHukumUmumTahun2008")
        assert "DirektoralJenderal" in hasil


class TestCleanPageText:
    def test_semua_lapisan_jalan_bersama(self) -> None:
        mentah = (
            "\u201cPemerin-\ntahan mengatur\u201d\n"
            "BagianTahun2008Nomor38\n"
            "...\n"
            "PRESIDEN REPUBLIK INDONESIA\n"
        )
        hasil = clean_page_text(mentah)
        assert "\u201c" not in hasil
        assert "Pemerintahan mengatur" in hasil
        assert "Bagian Tahun 2008 Nomor 38" in hasil
        assert "PRESIDEN" not in hasil
        assert "\f" not in hasil


# --------------------------------------------------------------------------
# Paket 2: penilaian kualitas chunk (flag-only).
# --------------------------------------------------------------------------


TEKS_SEHAT = (
    "Pelaporan pengaduan disampaikan secara tertulis kepada petugas pengelola "
    "di lokasi pelayanan. Setiap laporan dicatat dalam buku register yang "
    "disediakan oleh unit penanganan pengaduan masyarakat."
)

TEKS_SAMPAH = (
    "□ ◽ □ ◽ □ ◽ □ ◽ □ ◽ □ ◽ □ ◽ □ ◽ □ ◽ □ ◽ □ ◽ □ ◽ □\n"
    "◇ ◈ ◇ ◈ ◇ ◈ ◇ ◈ ◇ ◈ ◇ ◈ ◇ ◈ ◇ ◈ ◇ ◈ ◇ ◈ ◇ ◈ ◇ ◈ ◇ ◈ ◇\n"
    "▱ ▱ ▱ ▱ ▱ ▱ ▱ ▱ ▱ ▱ ▱ ▱ ▱ ▱ ▱ ▱ ▱ ▱ ▱ ▱ ▱ ▱ ▱ ▱ ▱ ▱ ▱ ▱\n"
    "▣ ▣ ▣ ▣ ▣ ▣ ▣ ▣ ▣ ▣ ▣ ▣ ▣ ▣ ▣ ▣ ▣ ▣ ▣ ▣ ▣ ▣ ▣ ▣ ▣ ▣ ▣ ▣\n"
    "▤ ▥ ▦ ▧ ▨ ▩ ▤ ▥ ▦ ▧ ▨ ▩ ▤ ▥ ▦ ▧ ▨ ▩ ▤ ▥ ▦ ▧ ▨ ▩ ▤ ▥ ▦ ▧\n"
)


class TestAssessChunkQuality:
    def test_teks_sehat_berflag_ok(self) -> None:
        hasil = assess_chunk_quality(TEKS_SEHAT)
        assert hasil.flag == CHUNK_FLAG_OK
        assert hasil.reasons == []

    def test_teks_sampah_berflag_low(self) -> None:
        hasil = assess_chunk_quality(TEKS_SAMPAH)
        assert hasil.flag == CHUNK_FLAG_LOW
        assert any("karakter" in reason for reason in hasil.reasons)

    def test_kata_terpecah_berflag_low(self) -> None:
        rusak = " ".join(
            ["Undang Undan g Tah un Nomor g Tahun 2008 a b c d e f g h i j"] * 3
        )
        hasil = assess_chunk_quality(rusak)
        assert hasil.flag == CHUNK_FLAG_LOW
        assert any("satu huruf" in reason or "panjang kata" in reason for reason in hasil.reasons)

    def test_confidence_rendah_menandai_chunk_teks_rapi(self) -> None:
        # Halaman yang tampak rapi tapi dibaca dengan keyakinan rendah tetap
        # meragukan: teks bisa salah tanpa terlihat dari statistiknya.
        hasil = assess_chunk_quality(TEKS_SEHAT, page_confidence=0.3)
        assert hasil.flag == CHUNK_FLAG_LOW
        assert any("confidence" in reason for reason in hasil.reasons)

    def test_confidence_tinggi_tidak_menandai(self) -> None:
        hasil = assess_chunk_quality(TEKS_SEHAT, page_confidence=0.9)
        assert hasil.flag == CHUNK_FLAG_OK

    def test_chunk_tanpa_kata_berflag_low(self) -> None:
        hasil = assess_chunk_quality("1234 5678 9012")
        assert hasil.flag == CHUNK_FLAG_LOW
        assert any("tidak ada kata" in reason for reason in hasil.reasons)

    def test_fragmen_pendek_berflag_low(self) -> None:
        hasil = assess_chunk_quality("Pasal 5")
        assert hasil.flag == CHUNK_FLAG_LOW


class TestToChunks:
    def test_form_feed_diganti_newline(self) -> None:
        span = TextSpan(
            content="Isi Pasal 5\fberlanjut di halaman berikutnya.",
            char_start=0,
            char_end=44,
            page_number=3,
        )
        chunks = IngestionService.to_chunks("doc1", [span])
        assert chunks[0].content == "Isi Pasal 5\nberlanjut di halaman berikutnya."

    def test_confidence_halaman_menandai_chunk(self) -> None:
        span = TextSpan(content=TEKS_SEHAT, char_start=0, char_end=len(TEKS_SEHAT), page_number=2)
        chunks = IngestionService.to_chunks("doc1", [span], {2: 0.3})
        assert chunks[0].quality_flag == CHUNK_FLAG_LOW

    def test_chunk_sehat_tanpa_confidence_berflag_ok(self) -> None:
        span = TextSpan(content=TEKS_SEHAT, char_start=0, char_end=len(TEKS_SEHAT), page_number=1)
        chunks = IngestionService.to_chunks("doc1", [span])
        assert chunks[0].quality_flag == CHUNK_FLAG_OK


# --------------------------------------------------------------------------
# Paket 3: gate bukti dua bar + skor bukti terkuat.
# --------------------------------------------------------------------------


def _entry(chunk_id: str, content: str, quality_flag: str | None = None) -> IndexEntry:
    return IndexEntry(
        chunk_id=chunk_id,
        document_id="doc1",
        document_name="peraturan.pdf",
        content=content,
        chunk_index=0,
        page_number=1,
        quality_flag=quality_flag,
    )


def _setup(retriever: HybridRetriever, content: str, embedding: list[float]) -> None:
    retriever.index([_entry("doc1_c1", content)])
    retriever._store.upsert(  # noqa: SLF001
        [
            VectorRecord(
                id="doc1_c1",
                embedding=embedding,
                metadata={"document_id": "doc1", "content": content},
            )
        ],
        "chunks",
    )


class TestGateDuaBar:
    def test_bukti_semantik_kuat_lolos_walau_kata_kunci_lemah(self) -> None:
        retriever = HybridRetriever(InMemoryVectorStore())
        embedding = [1.0, 0.0, 0.0]
        _setup(retriever, "pengelolaan pengaduan masyarakat", embedding)

        hasil = retriever.retrieve(
            "pengelolaan", embedding, top_k=3, threshold=0.78, keyword_strong_bar=0.99
        )
        # Skor vektor 1.0 ≥ threshold: lolos walau jalur kata kuncinya di
        # bawah bar leksikal.
        assert len(hasil) == 1
        assert hasil[0].vector_score == pytest.approx(1.0)

    def test_kata_kunci_di_bawah_bar_tidak_masuk_bukti_kuat(self) -> None:
        retriever = HybridRetriever(InMemoryVectorStore())
        # Embedding tersimpan tegak lurus query → jalur vektor mati; keputusan
        # sepenuhnya di jalur leksikal.
        _setup(retriever, "pengaduan pengaduan pengaduan pengaduan", [1.0, 0.0])
        query_embedding = [0.0, 1.0]

        skor_mentah = retriever._keyword_index.search("pengaduan", top_k=3)[0][1]  # noqa: SLF001
        keyword_norm = _normalized_keyword(skor_mentah)
        hasil = retriever.retrieve(
            "pengaduan",
            query_embedding,
            top_k=3,
            threshold=0.78,
            # Bar sengaja dipasang persis di atas bukti leksikal yang ada.
            keyword_strong_bar=min(keyword_norm + 0.01, 0.999),
        )
        assert hasil == []

    def test_kata_kunci_di_atas_bar_lolos_sebagai_bukti_kuat(self) -> None:
        retriever = HybridRetriever(InMemoryVectorStore())
        _setup(retriever, "pengaduan pengaduan pengaduan pengaduan", [1.0, 0.0])
        query_embedding = [0.0, 1.0]

        skor_mentah = retriever._keyword_index.search("pengaduan", top_k=3)[0][1]  # noqa: SLF001
        keyword_norm = _normalized_keyword(skor_mentah)
        hasil = retriever.retrieve(
            "pengaduan",
            query_embedding,
            top_k=3,
            threshold=0.78,
            keyword_strong_bar=max(keyword_norm - 0.01, 0.0),
        )
        assert len(hasil) == 1

    def test_skor_yang_ditampilkan_adalah_bukti_terkuat_bukan_fusi(self) -> None:
        retriever = HybridRetriever(InMemoryVectorStore())
        embedding = [1.0, 0.0, 0.0]
        _setup(retriever, "pengelolaan pengaduan masyarakat", embedding)

        hasil = retriever.retrieve(
            "pengelolaan", embedding, top_k=3, threshold=0.5
        )
        assert hasil
        # Kandidat tunggal membuat RRF ternormalisasi selalu 1.0; skor
        # terkuat justru harus di bawah itu (cosine 1.0 kecuali persis
        # identik di sini, BM25-nya kecil).
        assert hasil[0].score == pytest.approx(
            max(hasil[0].vector_score, _normalized_keyword(hasil[0].keyword_score))
        )

    def test_best_candidates_juga_memakai_bukti_terkuat(self) -> None:
        retriever = HybridRetriever(InMemoryVectorStore())
        embedding = [1.0, 0.0, 0.0]
        _setup(retriever, "pengelolaan pengaduan masyarakat", embedding)

        kandidat = retriever.best_candidates("pengelolaan", embedding, limit=3)
        assert kandidat
        assert kandidat[0].score == pytest.approx(
            max(
                kandidat[0].vector_score,
                _normalized_keyword(kandidat[0].keyword_score),
            )
        )


# --------------------------------------------------------------------------
# Paket 4: padanan kata & toleransi typo di BM25.
# --------------------------------------------------------------------------


@pytest.fixture
def stemming_on() -> None:
    configure_stemming(
        type("S", (), {"bm25_stemming_enabled": True})()  # type: ignore[arg-type]
    )
    yield
    configure_stemming(
        type("S", (), {"bm25_stemming_enabled": False})()  # type: ignore[arg-type]
    )


class TestPadananKata:
    def test_pengaduan_menemukan_dokumen_berisi_keluhan(
        self, stemming_on: None
    ) -> None:
        index = KeywordIndex()
        index.add("doc1_c1", "Keluhan masyarakat ditanggapi selama tujuh hari.")
        # "pengaduan" dan "keluhan" keduanya stem ke akar berbeda ("adu" vs
        # "keluh"); kamus padanan-lah yang menyatukannya.
        assert index.search("pengaduan masyarakat", top_k=3) != []

    def test_sinonim_tidak_mengubah_skor_token_asli(self) -> None:
        index = KeywordIndex()
        index.add("doc1_c1", "pengaduan ditanggapi")
        index.add("doc2_c1", "keluhan ditanggapi")
        hasil = dict(index.search("pengaduan ditanggapi", top_k=5))
        # Token asli berbobot 1.0, ekspansinya 0.8: dokumen yang benar-benar
        # memakai katanya harus menang.
        assert hasil["doc1_c1"] > hasil["doc2_c1"]


class TestFuzzyTypo:
    def test_typo_satu_huruf_ditemukan(self) -> None:
        index = KeywordIndex(enable_fuzzy=True)
        index.add("doc1_c1", "proses komplain dilakukan melalui aplikasi resmi")
        # "konplain" (n untuk m) jarak editnya 1 dari "komplain"; fuzzy
        # mengembalikannya dengan bobot 0.8.
        assert index.search("konplain", top_k=3) != []

    def test_fuzzy_mati_tidak_menebak(self) -> None:
        index = KeywordIndex(enable_fuzzy=False)
        index.add("doc1_c1", "proses komplain dilakukan melalui aplikasi resmi")
        assert index.search("konplain", top_k=3) == []

    def test_token_yang_ketemu_tidak_perlu_fuzzy(self) -> None:
        index = KeywordIndex(enable_fuzzy=True)
        index.add("doc1_c1", "komplain resmi")
        # Kata yang sudah punya postingan tidak diekspansi; skor murni BM25.
        hasil = index.search("komplain", top_k=3)
        assert hasil != []


class TestNormalizeQuery:
    def test_kutipan_keriting_dari_tempel_dokumen_diratakan(self) -> None:
        assert normalize_query("apa isi \u201cPasal 5\u201d\u2013\u201d7\u201d?") == (
            "apa isi \"Pasal 5\"-\"7\"?"
        )

    def test_pertanyaan_biasa_tidak_berubah(self) -> None:
        assert normalize_query("berapa batas waktu pengaduan?") == (
            "berapa batas waktu pengaduan?"
        )


# --------------------------------------------------------------------------
# Paket 5: penanda sumber meragukan di prompt.
# --------------------------------------------------------------------------


def _retrieved(quality_flag: str | None) -> RetrievedChunk:
    return RetrievedChunk(
        chunk=Chunk(
            id="doc1_c1",
            document_id="doc1",
            chunk_index=0,
            content=TEKS_SEHAT,
            page_number=3,
            quality_flag=quality_flag,
        ),
        document_name="peraturan.pdf",
        score=0.86,
        vector_score=0.86,
        keyword_score=0.0,
    )


class TestPromptFlagKualitas:
    def test_sumber_low_ditandai_di_prompt(self) -> None:
        prompt = build_context_prompt(
            question="bagaimana pelaporan pengaduan?",
            retrieved=[_retrieved("low")],
            history=[],
            max_history=0,
        )
        assert "Catatan kualitas" in prompt
        assert "kurang jelas" in prompt

    def test_sumber_sehat_tidak_ditandai(self) -> None:
        prompt = build_context_prompt(
            question="bagaimana pelaporan pengaduan?",
            retrieved=[_retrieved("ok")],
            history=[],
            max_history=0,
        )
        assert "Catatan kualitas" not in prompt

    def test_flag_tidak_dikirim_sebagai_kualitas_buruk(self) -> None:
        # None berarti "belum dinilai" (chunk lama), bukan buruk: tidak boleh
        # ikut ditandai.
        prompt = build_context_prompt(
            question="bagaimana pelaporan pengaduan?",
            retrieved=[_retrieved(None)],
            history=[],
            max_history=0,
        )
        assert "Catatan kualitas" not in prompt

    def test_aturan_catatan_awam_ada_di_kedua_prompt_sistem(self) -> None:
        for prompt in (SYSTEM_PROMPT, WEAK_EVIDENCE_SYSTEM_PROMPT):
            assert "Catatan kualitas" in prompt
            # Aturannya memerintahkan bahasa awam ke pengguna: frasa contoh
            # tanpa istilah teknis, dan larangan menyebut istilah itu eksplisit.
            assert "kurang jelas" in prompt
            assert "istilah teknis" in prompt


# --------------------------------------------------------------------------
# Small-to-big: pecahan Pasal panjang membawa badan utuhnya.
# --------------------------------------------------------------------------


class TestSmallToBig:
    def test_pecahan_pasal_panjang_membawa_parent_text(self) -> None:
        from app.services.ingestion.legal import build_legal_chunks

        body = "\n".join(
            f"({n}) Ayat {n} mengatur hal yang panjang dan rinci bersama tetangganya "
            "dalam satu badan pasal yang tidak muat dalam satu potongan saja."
            for n in range(1, 9)
        )
        dokumen = (
            "BAB I KETENTAN UMUM\nPasal 1\n"
            + body
            + "\nPasal 2\n(1) Pasal pendek."
        )
        spans = build_legal_chunks(dokumen, max_chars=300, overlap=50)
        pasal1 = [s for s in spans if s.section == "Pasal 1"]
        assert len(pasal1) > 1, "pasal seharusnya terpecah"
        for span in pasal1:
            assert span.parent_text is not None
            assert "Ayat 1" in span.parent_text and "Ayat 8" in span.parent_text
        pasal2 = [s for s in spans if s.section == "Pasal 2"]
        assert all(s.parent_text is None for s in pasal2)

    def test_parent_dipakai_sebagai_konteks_ekspansi(self) -> None:
        from app.models.domain import Chunk, RetrievedChunk
        from app.services.rag_service import RagService

        parent = "Badan pasal utuh dengan rujukan silang ke ayat (2)."
        retrieved = [
            RetrievedChunk(
                chunk=Chunk(
                    id="doc1_c5",
                    document_id="doc1",
                    chunk_index=4,
                    content="pecahan ayat (3)",
                    page_number=2,
                    parent_text=parent,
                ),
                document_name="peraturan.pdf",
                score=0.9,
                vector_score=0.9,
                keyword_score=0.0,
            )
        ]
        # _gather_neighbors bermethod instance tapi hanya menyentuh repository
        # untuk chunk tanpa parent; panggil lewat kelas tanpa membangun service.
        service = RagService.__new__(RagService)
        service._settings = type(
            "S", (), {"context_window_chunks": 1}
        )()
        neighbors = service._gather_neighbors(retrieved)
        assert neighbors[1][0].content == parent
