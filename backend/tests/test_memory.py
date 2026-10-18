"""Test memory store, cache, dan rate limit.

Yang paling penting di sini: rate limit harus benar-benar menahan, dan cache
harus benar-benar dipakai. Kalau salah satu tidak bekerja, kuota free tier
bisa habis tanpa disadari.
"""

from __future__ import annotations

import pytest

from app.core.config import Settings
from app.core.security import SlidingWindowLimiter, hash_passcode, verify_passcode
from app.models.domain import ChatMessage, MessageRole
from app.services.memory.rate_limit import RateLimiter
from app.services.memory.store import (
    ANSWER_CACHE_PREFIX,
    InMemoryStore,
    cache_key,
    dict_to_message,
    message_to_dict,
)


class TestSlidingWindow:
    def test_awal_tidak_diblokir(self) -> None:
        limiter = SlidingWindowLimiter(max_attempts=3, window_seconds=60)
        assert limiter.is_blocked("ip") is False

    def test_diblokir_setelah_mencapai_batas(self) -> None:
        limiter = SlidingWindowLimiter(max_attempts=3, window_seconds=60)
        for _ in range(3):
            limiter.record("ip")
        assert limiter.is_blocked("ip") is True

    def test_tidak_diblokir_di_bawah_batas(self) -> None:
        limiter = SlidingWindowLimiter(max_attempts=3, window_seconds=60)
        limiter.record("ip")
        limiter.record("ip")
        assert limiter.is_blocked("ip") is False

    def test_bucket_terpisah_untuk_ip_berbeda(self) -> None:
        limiter = SlidingWindowLimiter(max_attempts=2, window_seconds=60)
        limiter.record("ip-a")
        limiter.record("ip-a")
        # IP lain tidak boleh terpengaruh.
        assert limiter.is_blocked("ip-b") is False

    def test_retry_after_positif(self) -> None:
        limiter = SlidingWindowLimiter(max_attempts=1, window_seconds=60)
        limiter.record("ip")
        assert limiter.retry_after("ip") > 0

    def test_clear_membuka_akses(self) -> None:
        limiter = SlidingWindowLimiter(max_attempts=2, window_seconds=60)
        limiter.record("ip")
        limiter.record("ip")
        limiter.clear("ip")
        assert limiter.is_blocked("ip") is False


class TestPasscode:
    def test_passcode_benar_diterima(self) -> None:
        settings = Settings(access_passcode_sha256=hash_passcode("rahasia"))
        assert verify_passcode("rahasia", settings) is True

    def test_passcode_salah_ditolak(self) -> None:
        settings = Settings(access_passcode_sha256=hash_passcode("rahasia"))
        assert verify_passcode("salah", settings) is False

    def test_tanpa_hash_menolak_semua(self) -> None:
        # Kalau operator lupa mengisi env, gerbang harus menolak semua, bukan
        # menerima semua. Menolak semua lebih aman daripada membiarkan terbuka.
        assert verify_passcode("apa saja", Settings(access_passcode_sha256=None)) is False

    def test_kandidat_kosong_ditolak(self) -> None:
        settings = Settings(access_passcode_sha256=hash_passcode("rahasia"))
        assert verify_passcode("", settings) is False

    def test_hash_konsisten(self) -> None:
        assert hash_passcode("rahasia") == hash_passcode("rahasia")

    def test_hash_berbeda_untuk_berbeda(self) -> None:
        assert hash_passcode("a") != hash_passcode("b")

    def test_token_sesi_unik(self) -> None:
        from app.core.security import make_session_token  # noqa: PLC0415

        tokens = {make_session_token() for _ in range(100)}
        assert len(tokens) == 100
        assert len(tokens.pop()) >= 32


class TestInMemoryStore:
    async def test_simpan_dan_muat_sesi(self) -> None:
        store = InMemoryStore()
        await store.save_session("ses_1", [{"role": "user", "content": "halo"}], ttl=60)
        loaded = await store.load_session("ses_1")
        assert loaded is not None
        assert loaded[0]["content"] == "halo"

    async def test_muat_sesi_tidak_ada_none(self) -> None:
        assert await InMemoryStore().load_session("tidak-ada") is None

    async def test_sesi_kedaluwarsa_dianggap_hilang(self) -> None:
        store = InMemoryStore()
        await store.save_session("ses_1", [{"role": "user"}], ttl=-1)
        # TTL negatif berarti sudah kedaluwarsa, jadi tidak boleh dikembalikan.
        assert await store.load_session("ses_1") is None

    async def test_hapus_sesi(self) -> None:
        store = InMemoryStore()
        await store.save_session("ses_1", [{"role": "user"}], ttl=60)
        await store.delete_session("ses_1")
        assert await store.load_session("ses_1") is None

    async def test_daftar_sesi_hidup(self) -> None:
        store = InMemoryStore()
        await store.save_session("ses_1", [{"role": "user"}], ttl=60)
        await store.save_session("ses_2", [{"role": "user"}], ttl=60)
        await store.save_session("kadaluarsa", [{"role": "user"}], ttl=-1)
        assert set(await store.list_sessions()) == {"ses_1", "ses_2"}

    async def test_daftar_sesi_kosong(self) -> None:
        assert await InMemoryStore().list_sessions() == []

    async def test_cache_set_dan_get(self) -> None:
        store = InMemoryStore()
        await store.set_cached("kunci", {"jawaban": "isi"}, ttl=60)
        cached = await store.get_cached("kunci")
        assert cached is not None
        assert cached["jawaban"] == "isi"

    async def test_cache_tidak_ada(self) -> None:
        assert await InMemoryStore().get_cached("tidak-ada") is None

    async def test_cache_kedaluwarsa(self) -> None:
        store = InMemoryStore()
        await store.set_cached("kunci", {"jawaban": "isi"}, ttl=-1)
        assert await store.get_cached("kunci") is None

    async def test_hapus_berdasarkan_prefix(self) -> None:
        store = InMemoryStore()
        await store.save_session("ses_1", [{"role": "user"}], ttl=60)
        await store.save_session("ses_2", [{"role": "user"}], ttl=60)
        await store.set_cached("k", {"x": 1}, ttl=60)
        # Hanya sesi yang dihapus, cache harus tetap ada.
        assert await store.delete_by_prefix("chat:") == 2
        assert await store.list_sessions() == []
        assert await store.get_cached("k") is not None

    async def test_ping(self) -> None:
        assert await InMemoryStore().ping() is True


class TestCacheKey:
    def test_pertanyaan_sama_memberi_kunci_sama(self) -> None:
        assert cache_key("apa ini", None, 5) == cache_key("apa ini", None, 5)

    def test_pertanyaan_berbeda_memberi_kunci_berbeda(self) -> None:
        assert cache_key("apa ini", None, 5) != cache_key("apa itu", None, 5)

    def test_abai_case_dan_spasi_tepisah(self) -> None:
        assert cache_key("  APA INI ", None, 5) == cache_key("apa ini", None, 5)

    def test_dokumen_berbeda_memberi_kunci_berbeda(self) -> None:
        # Jawaban untuk dokumen berbeda jelas berbeda, jadi tidak boleh berbagi
        # entri cache.
        assert cache_key("sama", ["d1"], 5) != cache_key("sama", ["d2"], 5)

    def test_urutan_dokumen_tidak_penting(self) -> None:
        assert cache_key("sama", ["d1", "d2"], 5) == cache_key("sama", ["d2", "d1"], 5)

    def test_top_k_berbeda_memberi_kunci_berbeda(self) -> None:
        # top_k berbeda menghasilkan jumlah sumber berbeda, jadi jawabannya
        # juga berbeda.
        assert cache_key("sama", None, 3) != cache_key("sama", None, 10)

    def test_threshold_berbeda_memberi_kunci_berbeda(self) -> None:
        # Menaikkan ambang mengubah apakah retrieval lolos gate sama sekali,
        # jadi jawaban dari ambang lama tidak boleh lagi dipakai.
        assert cache_key("sama", None, 5, 0.5) != cache_key("sama", None, 5, 0.9)

    def test_scope_dokumen_memberi_kunci_berbeda(self) -> None:
        # Bug nyata: tanpa scope di kunci, sesi privat dokumen A menyajikan
        # jawaban yang dibuat dari dokumen B, kebocoran scope yang tidak
        # terlihat di UI karena jawabannya tetap membawa sitasi.
        assert cache_key("sama", None, 5, 0.82, "doc_a") != cache_key(
            "sama", None, 5, 0.82, "doc_b"
        )
        assert cache_key("sama", None, 5, 0.82, "doc_a") != cache_key(
            "sama", None, 5, 0.82, None
        )

    def test_scope_sama_memberi_kunci_sama(self) -> None:
        assert cache_key("sama", None, 5, 0.82, "doc_a") == cache_key(
            "sama", None, 5, 0.82, "doc_a"
        )

    def test_ambang_tidak_berubah_memberi_kunci_sama(self) -> None:
        assert cache_key("sama", None, 5, 0.5) == cache_key("sama", None, 5, 0.5)

    def test_kunci_berawalan_namespace_jawaban(self) -> None:
        # Prefix ini yang membuat cache jawaban bisa dihapus tanpa ikut
        # menghapus counter rate limit.
        assert cache_key("x", None, 5).startswith(ANSWER_CACHE_PREFIX)

    def test_kunci_panjang_terbatas(self) -> None:
        # Hash 64 hex + prefix namespace; bukan teks pertanyaan mentah.
        key = cache_key("x" * 10_000, None, 5)
        assert len(key) == len(ANSWER_CACHE_PREFIX) + 64


class TestMessageSerialization:
    def test_pesan_bulat_trip(self) -> None:
        message = ChatMessage(
            id="msg_1",
            role=MessageRole.USER,
            content="apa isi dokumen?",
            created_at="2026-01-01T00:00:00+00:00",
        )
        payload = message_to_dict(message)
        assert payload["role"] == "user"
        assert payload["content"] == "apa isi dokumen?"

    def test_flag_ungrounded_ikut_tersimpan(self) -> None:
        """Label "bukan dari dokumen" harus bertahan di storage.

        Kalau flag ini hilang saat dibaca ulang, jawaban lama yang dibuat dari
        pengetahuan umum akan terlihat bersumber pada dokumen begitu riwayat
        dibuka lagi, dan pengguna tidak punya cara mengetahuinya.
        """
        message = ChatMessage(
            id="msg_2",
            role=MessageRole.ASSISTANT,
            content="presiden pertama Indonesia adalah Soekarno",
            created_at="2026-01-01T00:00:00+00:00",
            ungrounded=True,
        )
        payload = message_to_dict(message)
        assert payload["ungrounded"] is True
        restored = dict_to_message(payload)
        assert restored.ungrounded is True

    def test_pesan_biasa_tidak_bertanda_ungrounded(self) -> None:
        message = ChatMessage(
            id="msg_3",
            role=MessageRole.ASSISTANT,
            content="dua hari kerja",
            created_at="2026-01-01T00:00:00+00:00",
        )
        restored = dict_to_message(message_to_dict(message))
        assert restored.ungrounded is False

    def test_pesan_dengan_sitasi_bulat_trip(self) -> None:
        from app.models.domain import Citation  # noqa: PLC0415

        message = ChatMessage(
            id="msg_2",
            role=MessageRole.ASSISTANT,
            content="jawabannya",
            created_at="2026-01-01T00:00:00+00:00",
            citations=[
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
        restored = dict_to_message(message_to_dict(message))
        assert restored.role is MessageRole.ASSISTANT
        assert len(restored.citations) == 1
        assert restored.citations[0].document_name == "a.pdf"
        assert restored.citations[0].page_number == 3

    def test_pesan_tanpa_sitasi_bulat_trip(self) -> None:
        message = ChatMessage(
            id="msg_3",
            role=MessageRole.ASSISTANT,
            content="tidak ditemukan",
            created_at="2026-01-01T00:00:00+00:00",
            not_found=True,
        )
        restored = dict_to_message(message_to_dict(message))
        assert restored.not_found is True
        assert restored.citations == []

    def test_payload_rusak_tidak_melempar(self) -> None:
        # Data dari Redis bisa saja rusak karena versi lama atau write
        # terputus; jangan sampai satu payload buruk menggagalkan seluruh
        # riwayat.
        restored = dict_to_message({"role": "assistant", "content": "x", "citations": "bukan list"})
        assert restored.citations == []


class TestRateLimiter:
    @pytest.fixture
    def limiter(self) -> RateLimiter:
        store = InMemoryStore()
        settings = Settings(query_max_per_session=3, query_window_seconds=60)
        return RateLimiter(store, settings)

    async def test_permintaan_pertama_boleh(self, limiter: RateLimiter) -> None:
        allowed, retry_after = await limiter.check("ses_1")
        assert allowed is True
        assert retry_after == 0

    async def test_ditahan_setelah_batas(self, limiter: RateLimiter) -> None:
        for _ in range(3):
            allowed, _ = await limiter.check("ses_1")
            assert allowed is True
        allowed, retry_after = await limiter.check("ses_1")
        assert allowed is False
        assert retry_after > 0

    async def test_bucket_terpisah(self, limiter: RateLimiter) -> None:
        for _ in range(3):
            await limiter.check("ses_1")
        # Sesi lain tidak boleh terpengaruh.
        allowed, _ = await limiter.check("ses_2")
        assert allowed is True

    async def test_permintaan_paralel_tidak_melewati_kuota(self) -> None:
        """Read-modify-write harus atomik.

        Tanpa lock, request yang datang bersamaan sama-sama membaca counter
        lama lalu sama-sama menulis, sehingga kuota terlewati tepat saat trafik
        paling tinggi, kondisi yang justru paling butuh rate limit.
        """
        import asyncio

        limiter = RateLimiter(
            InMemoryStore(),
            Settings(query_max_per_session=5, query_window_seconds=60),
        )
        results = await asyncio.gather(*[limiter.check("sama") for _ in range(20)])
        allowed = sum(1 for item, _ in results if item)
        assert allowed == 5

    async def test_reset_membuka_akses(self, limiter: RateLimiter) -> None:
        for _ in range(3):
            await limiter.check("ses_1")
        await limiter.reset("ses_1")
        allowed, _ = await limiter.check("ses_1")
        assert allowed is True

    async def test_jendela_bergeser_membuka_akses(self) -> None:
        # TTL pendek supaya jendela benar-benar bergeser.
        store = InMemoryStore()
        limiter = RateLimiter(store, Settings(query_max_per_session=1, query_window_seconds=1))
        allowed, _ = await limiter.check("ses_1")
        assert allowed is True
        allowed, _ = await limiter.check("ses_1")
        assert allowed is False

        import asyncio

        await asyncio.sleep(1.1)
        allowed, _ = await limiter.check("ses_1")
        assert allowed is True

    async def test_reset_menghapus_kunci_yang_benar(self) -> None:
        """Reset harus benar-benar mengosongkan counter, bukan kunci lain.

        Versi lama mengembalikan kunci yang sudah berprefiks ``cache:`` lalu
        menambahkan prefiks itu lagi saat menghapus, sehingga reset tidak
        pernah menghapus apa pun dan pemanggil tidak menyadarinya karena
        jumlah yang dihapus tidak diperiksa.
        """
        store = InMemoryStore()
        limiter = RateLimiter(store, Settings(query_max_per_session=1, query_window_seconds=60))
        await limiter.check("ses_1")
        await limiter.reset("ses_1")

        # Kalau reset gagal, pemanggilan berikutnya akan langsung ditahan.
        allowed, _ = await limiter.check("ses_1")
        assert allowed is True


class TestAtomisitasRateLimit:
    """Jaminan atomik harus ada di store, bukan di pemanggil.

    Alasannya: lock ``asyncio`` hanya berlaku untuk satu proses. Kalau aplikasi
    berjalan di dua instance, keduanya punya lock sendiri yang tidak saling
    tahu, jadi baca-ubah-tulis terpisah tetap bisa kehilangan pembaruan.
    Test di bawah meniru kondisi itu dengan store yang menyisipkan titik
    ``await`` di antara baca dan tulis, persis seperti perjalanan pulang-pergi
    ke Redis.
    """

    async def test_store_menyediakan_operasi_atomik(self) -> None:
        store = InMemoryStore()
        assert hasattr(store, "hit_sliding_window")

    async def test_counter_atomik_menahan_tepat_pada_batas(self) -> None:
        import asyncio

        store = InMemoryStore()
        hasil = await asyncio.gather(
            *[store.hit_sliding_window("ratelimit:x", 4, 60) for _ in range(30)]
        )
        boleh = sum(1 for izin, _ in hasil if izin)
        assert boleh == 4

    async def test_retry_after_masuk_akal(self) -> None:
        store = InMemoryStore()
        for _ in range(2):
            izin, _ = await store.hit_sliding_window("ratelimit:y", 2, 60)
            assert izin is True

        izin, retry_after = await store.hit_sliding_window("ratelimit:y", 2, 60)
        assert izin is False
        # Tidak boleh nol atau negatif: pemanggil memakai angka ini sebagai
        # header Retry-After, dan nilai nol membuat klien langsung mencoba lagi.
        assert 1 <= retry_after <= 61

    async def test_kunci_berbeda_tidak_saling_mengunci(self) -> None:
        store = InMemoryStore()
        for _ in range(3):
            await store.hit_sliding_window("ratelimit:a", 3, 60)
        izin, _ = await store.hit_sliding_window("ratelimit:b", 3, 60)
        assert izin is True
