"""Test provider LLM dan rantai fallback.

Yang paling penting di file ini: rantai fallback harus benar-benar pindah ke
provider berikutnya saat provider pertama kena 429, dan harus **berhenti**
saat gagalnya bersifat konfigurasi (API key salah), karena mencoba provider
lain dengan masalah yang sama hanya menambah lambat.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest

from app.core.config import Settings
from app.providers.base import ProviderError, build_fallback_chain, build_provider
from app.providers.groq import GroqProvider
from app.providers.mock import MockProvider
from app.providers.openai_compatible import (
    OllamaProvider,
    SGLangProvider,
    _extract_full_text,
    _extract_token,
)
from app.services.generation.generator import LLMChain


class StubProvider:
    """Provider yang perilakunya bisa dikontrol test."""

    def __init__(
        self,
        name: str,
        *,
        configured: bool = True,
        result: str = "jawaban",
        error: ProviderError | None = None,
    ) -> None:
        self.name = name
        self._configured = configured
        self._result = result
        self._error = error
        self.calls = 0

    def is_configured(self) -> bool:
        return self._configured

    async def stream(self, prompt: str, system: str | None = None) -> AsyncIterator[str]:
        self.calls += 1
        if self._error is not None:
            raise self._error
        for index in range(0, len(self._result), 4):
            yield self._result[index : index + 4]

    async def complete(self, prompt: str, system: str | None = None) -> str:
        self.calls += 1
        if self._error is not None:
            raise self._error
        return self._result


class TestChainComplete:
    async def test_provider_pertama_berhasil(self) -> None:
        first = StubProvider("a", result="dari a")
        chain = LLMChain([first, StubProvider("b", result="dari b")])
        result = await chain.complete("prompt")
        assert result.content == "dari a"
        assert result.provider_name == "a"
        assert result.degraded is False

    async def test_fallback_saat_retryable(self) -> None:
        first = StubProvider(
            "a", error=ProviderError("kuota habis", retryable=True, status_code=429)
        )
        second = StubProvider("b", result="dari b")
        result = await LLMChain([first, second]).complete("prompt")
        assert result.provider_name == "b"
        assert result.degraded is True
        assert first.calls == 1
        assert second.calls == 1

    async def test_berhenti_saat_bukan_retryable(self) -> None:
        # API key salah tidak akan diperbaiki oleh provider berikutnya, jadi
        # mencoba lagi hanya menambah lambat.
        first = StubProvider(
            "a", error=ProviderError("key ditolak", retryable=False, status_code=401)
        )
        second = StubProvider("b", result="dari b")
        with pytest.raises(ProviderError, match="Semua provider gagal"):
            await LLMChain([first, second]).complete("prompt")
        # Provider kedua tidak boleh dipanggil.
        assert second.calls == 0

    async def test_respons_kosong_memicu_percobaan_berikutnya(self) -> None:
        first = StubProvider("a", result="")
        second = StubProvider("b", result="isi sebenarnya")
        result = await LLMChain([first, second]).complete("prompt")
        assert result.content == "isi sebenarnya"

    async def test_semua_provider_gagal(self) -> None:
        chain = LLMChain(
            [
                StubProvider("a", error=ProviderError("x", retryable=True)),
                StubProvider("b", error=ProviderError("y", retryable=True)),
            ]
        )
        with pytest.raises(ProviderError) as info:
            await chain.complete("prompt")
        # Rincian kegagalan harus ikut, supaya mudah didiagnosis.
        assert "a: x" in str(info.value)
        assert "b: y" in str(info.value)

    async def test_rantai_kosong_melempar_pesan_jelas(self) -> None:
        with pytest.raises(ProviderError, match="Tidak ada provider"):
            LLMChain([])

    async def test_provider_tidak_terkonfigurasi_dilewati(self) -> None:
        configured = StubProvider("b", result="dari b")
        chain = LLMChain([StubProvider("a", configured=False), configured])
        assert chain.provider_names == ["b"]

    async def test_upaya_tercatat(self) -> None:
        first = StubProvider(
            "a", error=ProviderError("gagal", retryable=True)
        )
        result = await LLMChain([first, StubProvider("b", result="ok")]).complete("p")
        # Provider yang gagal harus dicoba tepat satu kali, lalu cadeia pindah.
        assert first.calls == 1
        # Rincian kegagalan ikut terbawa supaya mudah didiagnosis.
        assert result.attempts
        assert "a" in result.attempts[0]


class TestChainStream:
    async def test_stream_menghasilkan_token(self) -> None:
        chain = LLMChain([StubProvider("a", result="halo dunia")])
        tokens = [token async for token in chain.stream("prompt")]
        assert "".join(tokens) == "halo dunia"

    async def test_fallback_saat_provider_gagal_sebelum_token(self) -> None:
        first = StubProvider(
            "a", error=ProviderError("gagal", retryable=True, status_code=429)
        )
        chain = LLMChain([first, StubProvider("b", result="dari b")])
        tokens = [token async for token in chain.stream("prompt")]
        assert "".join(tokens) == "dari b"

    async def test_tidak_fallback_setelah_token_sudah_keluar(self) -> None:
        """Kalau sudah ada teks terkirim, mengganti provider akan menggandakan
        jawaban. Jadi stream berhenti dan ditandai terpotong."""

        class PartialFailure:
            name = "partial"

            def is_configured(self) -> bool:
                return True

            async def stream(self, prompt, system=None):  # noqa: ANN001, ANN202
                yield "sudah keluar"
                raise ProviderError("putus di tengah", retryable=True)

        chain = LLMChain([PartialFailure(), StubProvider("b", result="tidak boleh muncul")])
        tokens = [token async for token in chain.stream("prompt")]
        joined = "".join(tokens)
        assert "sudah keluar" in joined
        assert "tidak boleh muncul" not in joined
        # Penanda terpotong harus ada, supaya pengguna tahu jawabannya tidak utuh.
        assert "terpotong" in joined

    async def test_berhenti_saat_bukan_retryable(self) -> None:
        first = StubProvider(
            "a", error=ProviderError("key salah", retryable=False, status_code=401)
        )
        second = StubProvider("b", result="tidak dipanggil")
        chain = LLMChain([first, second])
        with pytest.raises(ProviderError):
            [token async for token in chain.stream("prompt")]
        assert second.calls == 0


class TestMockProvider:
    async def test_selalu_terkonfigurasi(self) -> None:
        assert MockProvider(Settings()).is_configured() is True

    async def test_menyalin_kutipan(self) -> None:
        provider = MockProvider(Settings())
        result = await provider.complete("Kutipan langsung dari dokumen:\n\nIsi chunk.")
        # Provider ini bukan LLM, dan mengatakannya sendiri di jawaban.
        assert "Isi chunk." in result
        assert "bukan sintesis LLM" in result

    async def test_prompt_kosong_memberi_pesan_jujur(self) -> None:
        result = await MockProvider(Settings()).complete("")
        assert "Tidak ada konteks" in result

    async def test_streaming_memberi_potongan(self) -> None:
        provider = MockProvider(Settings())
        tokens = [
            token
            async for token in provider.stream(
                "Kutipan langsung dari dokumen:\n\nTeks panjang sekali."
            )
        ]
        # Provider harus benar-benar streaming, bukan satu string panjang.
        assert len(tokens) > 1


class TestSseParsing:
    def test_token_dari_delta(self) -> None:
        line = 'data: {"choices":[{"delta":{"content":"halo"}}]}'
        assert _extract_token(line) == "halo"

    def test_baris_komentar_diabaikan(self) -> None:
        assert _extract_token(": keep-alive") == ""

    def test_penanda_done_diabaikan(self) -> None:
        assert _extract_token("data: [DONE]") == ""

    def test_json_rusak_diabaikan(self) -> None:
        assert _extract_token("data: {bukan json") == ""

    def test_tanpa_content_diabaikan(self) -> None:
        assert _extract_token('data: {"choices":[{"delta":{}}]}') == ""

    def test_payload_kosong_diabaikan(self) -> None:
        assert _extract_token("data: ") == ""

    def test_ambil_teks_lengkap(self) -> None:
        payload = {
            "choices": [
                {"message": {"content": "jawaban lengkap", "role": "assistant"}}
            ]
        }
        assert _extract_full_text(payload) == "jawaban lengkap"

    def test_payload_bukan_dict_aman(self) -> None:
        assert _extract_full_text("bukan dict") == ""
        assert _extract_full_text({"choices": []}) == ""


class TestProviderKonfigurasi:
    def test_groq_tanpa_api_key_tidak_terkonfigurasi(self) -> None:
        settings = Settings(groq_api_key=None)
        assert GroqProvider(settings).is_configured() is False

    def test_groq_dengan_api_key_terkonfigurasi(self) -> None:
        assert GroqProvider(Settings(groq_api_key="kuncinya")).is_configured() is True

    def test_ollama_selalu_terkonfigurasi(self) -> None:
        # Provider lokal tidak butuh API key, hanya server yang hidup.
        assert OllamaProvider(Settings()).is_configured() is True

    def test_sglang_selalu_terkonfigurasi(self) -> None:
        assert SGLangProvider(Settings()).is_configured() is True

    def test_nama_provider(self) -> None:
        settings = Settings()
        assert GroqProvider(settings).name == "groq"
        assert OllamaProvider(settings).name == "ollama"
        assert SGLangProvider(settings).name == "sglang"


class TestBuildProvider:
    def test_default_mock(self) -> None:
        assert build_provider(Settings()).name == "mock"

    def test_pilih_ollama(self) -> None:
        assert build_provider(Settings(llm_provider="ollama")).name == "ollama"

    def test_pilih_groq(self) -> None:
        assert build_provider(Settings(llm_provider="groq")).name == "groq"

    def test_provider_tidak_dikenal_ditolak_saat_konfigurasi(self) -> None:
        """Nama provider salah harus ditolak saat konfigurasi, bukan saat request.

        Validasi di ``Settings`` lebih awal daripada di ``build_provider``:
        kesalahan konfigurasi ketahuan saat aplikasi start, bukan setelah
        pengguna sudah menunggu Streaming.
        """
        from pydantic import ValidationError

        with pytest.raises(ValidationError, match="llm_provider"):
            Settings(llm_provider="tidak-ada")  # type: ignore[arg-type]

    def test_build_provider_melempar_untuk_nilai_di_luar_registry(self) -> None:
        """Pertahanan kedua kalau ``Settings`` dilewati (misal di test)."""
        config = Settings()
        # Simulasi nilai yang lolos validasi, misalnya config yang dimuat
        # ulang dari sumber lain.
        object.__setattr__(config, "llm_provider", "tidak-ada")
        with pytest.raises(ValueError, match="tidak dikenal"):
            build_provider(config)

    def test_rantai_menyertakan_provider_aktif_lebih_dulu(self) -> None:
        settings = Settings(llm_provider="ollama", llm_fallback_chain=["groq"])
        names = [provider.name for provider in build_fallback_chain(settings)]
        assert names[0] == "ollama"
        assert "groq" in names

    def test_rantai_tanpa_duplikat(self) -> None:
        settings = Settings(llm_provider="groq", llm_fallback_chain=["groq", "ollama"])
        names = [provider.name for provider in build_fallback_chain(settings)]
        # Provider yang sama tidak boleh dicoba dua kali.
        assert names == ["groq", "ollama"]

    def test_fallback_chain_dipisah_dari_string(self) -> None:
        settings = Settings(llm_fallback_chain="groq, ollama")
        assert settings.llm_fallback_chain == ["groq", "ollama"]

    def test_provider_fallback_tidak_dikenal_ditolak(self) -> None:
        with pytest.raises(ValueError, match="tidak dikenal"):
            Settings(llm_fallback_chain="tidak-ada")


class TestSettingsEfektif:
    def test_rantai_efektif_mulai_dari_provider_aktif(self) -> None:
        settings = Settings(llm_provider="groq", llm_fallback_chain="ollama,sglang")
        assert settings.effective_fallback_chain == ["groq", "ollama", "sglang"]

    def test_rantai_efektif_menghapus_duplikat(self) -> None:
        settings = Settings(llm_provider="groq", llm_fallback_chain="ollama,groq")
        assert settings.effective_fallback_chain == ["groq", "ollama"]

    def test_mode_sqlite_tanpa_supabase(self) -> None:
        settings = Settings(supabase_url=None, supabase_service_key=None)
        assert settings.is_sqlite_mode is True

    def test_mode_supabase_ada_keduanya(self) -> None:
        settings = Settings(
            supabase_url="https://contoh.supabase.co", supabase_service_key="kunci"
        )
        assert settings.is_sqlite_mode is False

    def test_mode_memory_tanpa_redis(self) -> None:
        settings = Settings(redis_url=None, upstash_redis_url=None)
        assert settings.is_memory_store_mode is True

    def test_mode_redis_ada(self) -> None:
        assert Settings(redis_url="redis://localhost:6379").is_memory_store_mode is False


class TestProviderError:
    def test_retryable_bersamaan_default_false(self) -> None:
        assert ProviderError("x").retryable is False

    def test_status_code_tersimpan(self) -> None:
        assert ProviderError("x", status_code=429).status_code == 429
