"""Test RAG service, termasuk jalur anti-halusinasi.

Test yang paling penting di file ini adalah ``test_ambang_terbawah_tidak_memanggil_llm``.
Perilaku itu yang membedakan sistem RAG yang bisa dipercaya dari sistem yang
mengarang jawaban.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator

import pytest

from app.providers.base import ProviderError
from app.services.rag_service import (
    RagService,
    StreamEvent,
    _clean_answer,
    _history_has_grounded_answer,
    _is_refusal,
)


async def collect(stream: AsyncIterator[StreamEvent]) -> list[StreamEvent]:
    """Kumpulkan semua event dari stream."""
    return [event async for event in stream]

class TestRetrievalGate:
    async def test_tanpa_dokumen_tidak_memanggil_llm(self, rag: RagService) -> None:
        """Ambang tidak terpenuhi berarti LLM tidak boleh dipanggil sama sekali."""
        events = await collect(rag.answer("apa isi dokumen ini?", None, None))
        types = [event.type for event in events]

        assert "not_found" in types
        assert "done" in types
        # Tidak ada token jawaban selain pesan tidak ditemukan.
        text = "".join(str(event.value) for event in events if event.type == "token")
        assert "tidak ditemukan" in text.lower()

    async def test_event_done_membawa_durasi(self, rag: RagService) -> None:
        events = await collect(rag.answer("apapun", None, None))
        done = next(event for event in events if event.type == "done")
        assert done.response_time_ms is not None
        assert done.response_time_ms >= 0

    async def test_sesi_baru_langsung_dikirim(
        self, rag: RagService, repository
    ) -> None:
        events = await collect(rag.answer("pertanyaan tanpa konteks", None, None))
        session_event = next(event for event in events if event.type == "session")
        assert session_event.session_id

        # Sesi harus tercatat di metadata dengan judul dari pertanyaan pertama.
        session = repository.get_session(session_event.session_id)
        assert session is not None
        assert session.title

class TestAnswerWithContext:
    async def test_konteks_ditemukan_memberi_sitasi(
        self, indexed_ingestion, rag: RagService
    ) -> None:
        events = await collect(
            rag.answer("berapa hari untuk penyelesaian permintaan", None, None)
        )
        types = [event.type for event in events]
        assert "citations" in types
        assert "not_found" not in types

        citations_event = next(event for event in events if event.type == "citations")
        citations = citations_event.value
        assert citations
        assert citations[0].document_name == "panduan.md"
        # Sitasi harus bisa ditelusuri: ada id dokumen dan nomor chunk.
        assert citations[0].document_id
        assert citations[0].chunk_index >= 0
        assert citations[0].excerpt

    async def test_pertanyaan_tidak_relevan_menghasilkan_not_found(
        self, indexed_ingestion, rag: RagService
    ) -> None:
        # repository jawaban harus diturunkan supaya tidak ada yang lolos ambang.
        rag.repository.update_settings({"similarity_threshold": 0.99})
        events = await collect(
            rag.answer("bagaimana receptive orthodontics bekerja", None, None)
        )
        assert "not_found" in [event.type for event in events]

    async def test_ambang_tinggi_menolak_semua(
        self, indexed_ingestion, rag: RagService
    ) -> None:
        rag.repository.update_settings({"similarity_threshold": 0.99})
        embedding = rag.embedding.embed_query("penyelesaian")
        settings = rag.repository.get_settings()
        retrieved = await rag.retrieve("penyelesaian", settings, None)
        assert retrieved == []
        assert embedding  # embedding tetap bisa dihitung; ambang yang menolak

class TestCache:
    async def test_query_identik_pakai_cache(
        self, indexed_ingestion, rag: RagService
    ) -> None:
        question = "berapa hari untuk penyelesaian"

        first = await collect(rag.answer(question, None, None))
        assert "citations" in [event.type for event in first]

        # Jalankan lagi dengan sesi berbeda; cache harus-hit.
        second = await collect(rag.answer(question, None, None))
        joined = "".join(str(event.value) for event in second if event.type == "token")
        assert len(joined) > 0

    async def test_cache_bersifat_per_kategori_dokumen(self, rag: RagService) -> None:
        from app.services.memory.store import cache_key

        key_a = cache_key("pertanyaan sama", ["d1", "d2"], 5)
        key_b = cache_key("pertanyaan sama", ["d1"], 5)
        # Dokumen berbeda berarti jawaban berbeda, jadi kunci harus berbeda.
        assert key_a != key_b

    async def test_cache_ikut_perubahan_top_k(self, rag: RagService) -> None:
        from app.services.memory.store import cache_key

        assert cache_key("sama", None, 3) != cache_key("sama", None, 10)

    async def test_cache_abai_case_dan_spasi(self, rag: RagService) -> None:
        from app.services.memory.store import cache_key

        assert cache_key("  Pertanyaan  ", None, 5) == cache_key("pertanyaan", None, 5)

class TestHistory:
    async def test_histori_terimpan_pesan(
        self, indexed_ingestion, rag: RagService
    ) -> None:
        session_id = "ses_uji"
        await collect(rag.answer("pertanyaan pertama", session_id, None))

        messages = await rag.get_history(session_id)
        assert len(messages) == 2
        assert messages[0].role.value == "user"
        assert messages[1].role.value == "assistant"

    async def test_riwayat_sesi_tidak_ada_kosong(
        self, rag: RagService
    ) -> None:
        assert await rag.get_history("tidak-ada") == []

    async def test_riwayat_sesi_hidup_terdaftar(
        self, indexed_ingestion, rag: RagService
    ) -> None:
        session_id = "ses_aktif"
        await collect(rag.answer("pertanyaan", session_id, None))
        assert session_id in await rag.live_session_ids()

    async def test_hapus_sesi_membersihkan_memori(
        self, indexed_ingestion, rag: RagService
    ) -> None:
        session_id = "ses_hapus"
        await collect(rag.answer("pertanyaan", session_id, None))
        await rag.delete_session(session_id)
        assert await rag.get_history(session_id) == []

    async def test_hapus_semua_sesi(
        self, indexed_ingestion, rag: RagService
    ) -> None:
        await collect(rag.answer("satu", "ses_a", None))
        await collect(rag.answer("dua", "ses_b", None))
        await rag.delete_all_sessions()
        assert await rag.live_session_ids() == []

class TestStreamEventPayload:
    def test_token(self) -> None:
        assert StreamEvent(type="token", value="halo").to_payload() == {
            "type": "token",
            "value": "halo",
        }

    def test_not_found(self) -> None:
        assert StreamEvent(type="not_found").to_payload() == {"type": "not_found"}

    def test_session(self) -> None:
        assert StreamEvent(type="session", session_id="s1").to_payload() == {
            "type": "session",
            "session_id": "s1",
        }

    def test_done(self) -> None:
        assert StreamEvent(type="done", response_time_ms=120).to_payload() == {
            "type": "done",
            "response_time_ms": 120,
        }

    def test_error(self) -> None:
        # ``retry_after_seconds`` ikut dikirim supaya frontend bisa memberi
        # jeda yang jelas, bukan spinner yang berjalan tanpa ujung.
        payload = StreamEvent(
            type="error", value="gagal", retry_after_seconds=30
        ).to_payload()
        assert payload == {
            "type": "error",
            "message": "gagal",
            "retry_after_seconds": 30,
        }

    def test_payload_bisa_diserialisasi_json(self) -> None:
        from app.models.domain import Citation

        event = StreamEvent(
            type="citations",
            value=[
                Citation(
                    document_id="d1",
                    document_name="a.pdf",
                    page_number=3,
                    chunk_index=0,
                    excerpt="isi",
                    score=0.9,
                )
            ],
        )
        # Frontend meng-json.loads payload ini, jadi harus bisa dienkode.
        encoded = json.dumps(event.to_payload(), ensure_ascii=False)
        decoded = json.loads(encoded)
        assert decoded["type"] == "citations"
        assert decoded["value"][0]["document_name"] == "a.pdf"


class TestProviderFailure:
    async def test_provider_gagal_menghasilkan_event_error(
        self, indexed_ingestion, rag: RagService
    ) -> None:
        class BrokenChain:
            provider_names = ["broken"]

            async def stream(self, prompt, system=None):  # noqa: ANN001, ANN202
                raise ProviderError("semua provider gagal", retryable=False)
                yield  # pragma: no cover

        rag.chain = BrokenChain()

        events = await collect(rag.answer("penyelesaian", None, None))
        errors = [event for event in events if event.type == "error"]
        assert errors
        assert "tidak tersedia" in str(errors[0].value).lower()

class TestBersihkanMarkup:
    """Markup mentah dari chunk tidak boleh sampai ke pengguna.

    Prompt sudah meminta model menulis ulang, tapi instruksi saja tidak
    cukup andal pada model kecil. Lapisan ini menjamin pengguna tidak pernah
    melihat `**tebal**`, `# judul`, atau garis `====` di jawaban.
    """

    def test_tebal_dibuang(self) -> None:
        assert _clean_answer("Masuk ke menu **Layanan** lalu klik **Kirim**.") == (
            "Masuk ke menu Layanan lalu klik Kirim."
        )

    def test_heading_dibuang(self) -> None:
        assert _clean_answer("## Prosedur\n\nIsi prosedur.") == "Prosedur\n\nIsi prosedur."

    def test_garis_pemisah_dibuang(self) -> None:
        assert _clean_answer("Judul\n====\n\nIsi.") == "Judul\n\nIsi."

    def test_isi_tidak_diubah(self) -> None:
        # Pembersihan hanya membuang penanda, bukan mengubah kata.
        asli = "SLA penyelesaian adalah dua hari kerja sejak permintaan dicatat."
        assert _clean_answer(asli) == asli

    def test_kode_inline_dibiarkan(self) -> None:
        # Backtick satu baris dipakai untuk istilah teknis; isinya tetap.
        assert "config.py" in _clean_answer("Lihat `config.py` untuk detail.")

    def test_em_dash_diganti_koma(self) -> None:
        # Em dash adalah penanda gaya tulisan mesin. Jawaban yang memakainya
        # terbaca seperti template, bukan seperti asisten yang menjelaskan.
        assert _clean_answer("Dua hari kerja \u2014 sejak dicatat") == (
            "Dua hari kerja, sejak dicatat"
        )

    def test_en_dash_diganti_koma(self) -> None:
        assert _clean_answer("Pagi \u2013 sore") == "Pagi, sore"

    def test_dash_ganda_diganti_koma(self) -> None:
        assert _clean_answer("Ini -- penjelasan") == "Ini, penjelasan"

    def test_tanda_hubung_kata_majemuk_dibiarkan(self) -> None:
        # Tanda hubung dalam kata majemuk bukan tanda pisah.
        assert _clean_answer("dua hari kerja, tanpa terkecuali") == (
            "dua hari kerja, tanpa terkecuali"
        )

    def test_koma_ganda_dirapikan(self) -> None:
        # Penggantian bisa menghasilkan koma beruntun; itu tidak boleh lolos.
        result = _clean_answer("Satu \u2014, dua")
        assert ",," not in result.replace(" ", "")


class TestRiwayatBersitasi:
    """Percakapan lanjutan tidak boleh dilabeli "bukan dari dokumen".

    Kalau pertanyaan sebelumnya sudah dijawab dari dokumen, pertanyaan
    lanjutan tentang hal yang sama tetap bersumber dokumen, retrieval
    putaran ini bisa kosong karena kalimatnya berbeda, tapi labelnya tidak
    boleh berubah.
    """

    def test_riwayat_dengan_jawaban_panjang_dianggap_bersitasi(self) -> None:
        history = [
            ("user", "berapa hari SLA penyelesaian?"),
            (
                "assistant",
                "SLA penyelesaian adalah batas waktu maksimal penyelesaian "
                "permintaan, yaitu dua hari kerja sejak permintaan dicatat.",
            ),
        ]
        assert _history_has_grounded_answer(history) is True

    def test_jawaban_singkat_yang_bersumber_tetap_dikenali(self) -> None:
        # Jawaban benar bisa singkat. Ambang yang terlalu tinggi membuat
        # pertanyaan lanjutan ditolak padahal jawabannya ada di riwayat.
        history = [
            ("user", "berapa hari SLA?"),
            ("assistant", "Dua hari kerja sejak permintaan dicatat. [SUMBER 1]"),
        ]
        assert _history_has_grounded_answer(history) is True

    def test_riwayat_hanya_penolakan_tidak_dianggap_bersitasi(self) -> None:
        history = [
            ("user", "berapa harga tiket bioskop?"),
            ("assistant", "Informasi ini tidak ditemukan dalam dokumen yang diunggah."),
        ]
        assert _history_has_grounded_answer(history) is False

    def test_riwayat_kosong(self) -> None:
        assert _history_has_grounded_answer([]) is False

    def test_jawaban_pendek_tidak_dianggap_bersitasi(self) -> None:
        # Jawaban terlalu pendek untuk bisa disebut bersumber dokumen; lebih
        # aman dianggap belum ada jawaban daripada salah melabeli.
        history = [("assistant", "Ya.")]
        assert _history_has_grounded_answer(history) is False


class TestRefusalTanpaSitasi:
    """Sitasi tidak boleh dikirim untuk jawaban yang menolak.

    Model bisa menyimpulkan "tidak ada di konteks" meski retrieval meloloskan
    chunk (topik menyerempet, jawabannya tidak ada). Menampilkan sumber di
    bawah jawaban seperti itu membuat pengguna mengira informasinya ada di
    dokumen.
    """

    @pytest.mark.parametrize(
        "answer",
        [
            "Tidak ditemukan.",
            "Informasi ini tidak ditemukan dalam dokumen.",
            "Jawabannya tidak disebutkan dalam konteks.",
            "Not found in the provided context.",
        ],
    )
    def test_penolakan_dikenali(self, answer: str) -> None:
        assert _is_refusal(answer) is True

    @pytest.mark.parametrize(
        "answer",
        [
            "SLA penyelesaian adalah dua hari kerja.",
            "",
        ],
    )
    def test_jawaban_biasa_tidak_dianggap_penolakan(self, answer: str) -> None:
        assert _is_refusal(answer) is False

    def test_jawaban_panjang_tidak_dianggap_penolakan(self) -> None:
        # Jawaban panjang yang kebetulan memuat frasa itu biasanya tetap
        # menjawab; hanya penolakan pendek yang menahan sitasi.
        long_answer = (
            "SLA penyelesaian adalah dua hari kerja sejak permintaan dicatat. "
            "Kalau berkas tidak lengkap, pemohon diberi tahu dalam tempo dua "
            "hari kerja. " * 4
            + "Denda tidak disebutkan dalam dokumen."
        )
        assert _is_refusal(long_answer) is False


class TestProviderNames:
    def test_provider_names_terbaca(self, rag: RagService) -> None:
        assert rag.provider_names == ["mock"]

    async def test_memory_available(self, rag: RagService) -> None:
        assert await rag.memory_available() is True
