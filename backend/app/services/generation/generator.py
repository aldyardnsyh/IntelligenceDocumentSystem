"""Generator jawaban dengan rantai fallback provider.

Tanggung jawab modul ini:

- Menjalankan model dengan prompt yang sudah terikat kutipan.
- Berpindah ke provider berikutnya kalau yang sekarang gagal secara retryable
  (kuota habis, provider tidak merespons).
- Mengembalikan jawaban lengkap *dan*(event token), supaya bisa dipakai untuk
  streaming maupun evaluasi batch.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from typing import TypeVar

from app.providers.base import LLMProvider, ProviderError
from app.services.generation.prompts import SYSTEM_PROMPT

logger = logging.getLogger(__name__)

T = TypeVar("T")


@dataclass(slots=True)
class GenerationResult:
    """Hasil generasi.

    ``provider_name`` dicatat supaya analitik bisa melihat provider mana yang
    benar-benar dipakai. Kalau fallback aktif, itu informasi berguna.
    """

    content: str
    provider_name: str
    attempts: list[str] = field(default_factory=list)
    degraded: bool = False
    error: str | None = None


@dataclass(slots=True)
class StreamChunk:
    """Satu unit hasil streaming.

    `token` berisi teks jawaban; `degraded` menandai bahwa provider gagal di
    tengah setelah sebagian teks terkirim. Keduanya dipisah supaya penanda
    keadaan tidak ikut tersimpan sebagai isi jawaban.
    """

    token: str = ""
    degraded: bool = False


class LLMChain:
    """Rantai provider dengan fallback otomatis.

    Konsepnya satu, provider-nya banyak. Kalau provider pertama gagal
    karena alasan yang sementara (429, timeout, server tidak hidup), provider
    berikutnya dicoba. Kalau gagalnya konfigurasi (API key salah), berhenti di
    situ, karena provider berikutnya punya masalah sendiri.
    """

    def __init__(
        self,
        providers: list[LLMProvider],
        max_retries: int = 2,
        base_backoff_seconds: float = 1.0,
    ) -> None:
        self._providers = [provider for provider in providers if provider.is_configured()]
        # Backoff eksponensial dipakai untuk 429/5xx: batas free tier sering
        # hanya sesaat, jadi pindah provider langsung bisa membuat semua
        # provider kena limit di request yang sama. `LLM_MAX_RETRIES` yang
        # dulu ada di config tidak pernah dibaca di mana pun.
        self._max_retries = max(0, max_retries)
        self._backoff = base_backoff_seconds
        if not self._providers:
            # ``ProviderError``, bukan ``ValueError``. Kegagalan ini adalah
            # kondisi runtime (semua provider ternyata tidak terkonfigurasi),
            # bukan kesalahan argumen pemanggil. Dengan satu tipe exception,
            # penanganan error di satu tempat cukup untuk dua jenis kegagalan.
            raise ProviderError(
                "Tidak ada provider yang terkonfigurasi. "
                "Set GROQ_API_KEY, atau jalankan Ollama, atau pakai LLM_PROVIDER=mock.",
                retryable=False,
            )

    def _retry_delay(self, attempt: int, error: ProviderError) -> float:
        """Tunggu sebelum mencoba lagi: ``Retry-After`` provider, atau backoff."""
        if error.retry_after_seconds:
            return min(float(error.retry_after_seconds), 10.0)
        return min(self._backoff * (2**attempt), 8.0)

    async def _with_retry(self, provider: LLMProvider, call: Callable[[], Awaitable[T]]) -> T:
        """Jalankan satu panggilan provider dengan percobaan ulang."""
        attempt = 0
        while True:
            try:
                return await call()
            except ProviderError as exc:
                if attempt >= self._max_retries or not exc.retryable:
                    raise
                delay = self._retry_delay(attempt, exc)
                attempt += 1
                logger.info(
                    "Provider %s gagal sementara, mencoba lagi dalam %.1fs (%d/%d): %s",
                    provider.name,
                    delay,
                    attempt,
                    self._max_retries,
                    exc,
                )
                await asyncio.sleep(delay)

    @property
    def provider_names(self) -> list[str]:
        return [provider.name for provider in self._providers]

    @property
    def providers(self) -> list[LLMProvider]:
        """Provider aktif, untuk shutdown dan diagnostik."""
        return list(self._providers)

    async def complete(self, prompt: str, system: str | None = SYSTEM_PROMPT) -> GenerationResult:
        """Jawaban lengkap, mencoba provider satu per satu."""
        attempts: list[str] = []
        last_error: ProviderError | None = None

        for index, provider in enumerate(self._providers):
            try:
                content = await self._with_retry(
                    provider,
                    lambda current=provider: current.complete(prompt, system),
                )
            except ProviderError as exc:
                attempts.append(f"{provider.name}: {exc}")
                last_error = exc
                if not exc.retryable:
                    break
                logger.warning("Provider %s gagal, mencoba berikutnya: %s", provider.name, exc)
                continue

            if not content.strip():
                # Respons kosong bukan kegagalan jaringan, tapi tidak berguna.
                # Provider berikutnya mungkin lebih berhasil.
                attempts.append(f"{provider.name}: respons kosong")
                last_error = ProviderError("Provider mengembalikan jawaban kosong.", retryable=True)
                continue

            return GenerationResult(
                content=content,
                provider_name=provider.name,
                attempts=attempts,
                degraded=index > 0,
            )

        raise ProviderError(
            "Semua provider gagal. " + " | ".join(attempts),
            retryable=False,
            status_code=last_error.status_code if last_error else None,
        )

    async def stream(
        self,
        prompt: str,
        system: str | None = SYSTEM_PROMPT,
    ) -> AsyncIterator[str]:
        """Stream token, dengan fallback kalau provider gagal di tengah.

        Penting: kalau provider sudah sempat mengeluarkan beberapa token lalu
        gagal, stream **tidak** dialihkan ke provider berikutnya, karena itu
        akan menggandakan jawaban dua kali. Token yang sudah keluar tetap
        dipakai.

        Penanda pemotongan dikirim sebagai event terpisah
        (``StreamChunk.degraded``), bukan sebagai teks. Kalau penandanya ikut
        masih masuk ke teks jawaban, string itu ikut tersimpan di cache dan di histori
        sebagai bagian jawaban yang sah, dan pembacaan berikutnya
        mendapatkan jawaban yang permanen mengandung peringatan.
        """
        attempts: list[str] = []
        stop_chain = False

        for provider in self._providers:
            emitted = False
            attempt = 0
            while True:
                try:
                    async for token in provider.stream(prompt, system):
                        emitted = True
                        yield StreamChunk(token=token)
                    break
                except ProviderError as exc:
                    if emitted:
                        attempts.append(f"{provider.name}: {exc}")
                        logger.warning(
                            "Provider %s gagal saat streaming: %s",
                            provider.name,
                            exc,
                        )
                        # Sudah ada teks yang terkirim ke pengguna. Mengganti
                        # provider sekarang akan mengulang jawaban.
                        yield StreamChunk(degraded=True)
                        return
                    if attempt < self._max_retries and exc.retryable:
                        # Belum ada satu pun token keluar, jadi mencoba lagi
                        # tidak mungkin menggandakan jawaban.
                        delay = self._retry_delay(attempt, exc)
                        attempt += 1
                        logger.info(
                            "Provider %s gagal sementara sebelum stream, "
                            "mencoba lagi dalam %.1fs (%d/%d): %s",
                            provider.name,
                            delay,
                            attempt,
                            self._max_retries,
                            exc,
                        )
                        await asyncio.sleep(delay)
                        continue
                    attempts.append(f"{provider.name}: {exc}")
                    if not exc.retryable:
                        # Masalah konfigurasi: provider berikutnya punya
                        # masalah sendiri, mencoba hanya menambah lambat.
                        stop_chain = True
                    else:
                        logger.warning(
                            "Provider %s gagal, mencoba berikutnya: %s", provider.name, exc
                        )
                    break

            if stop_chain:
                break
            if not emitted:
                # Tidak ada token sama sekali: provider berikutnya mungkin
                # lebih berhasil.
                attempts.append(f"{provider.name}: tidak ada token")
                continue
            return

        raise ProviderError("Semua provider gagal saat streaming. " + " | ".join(attempts))


def build_chain(settings: object) -> LLMChain:
    """Bangun rantai dari konfigurasi aplikasi."""
    from app.providers.base import build_fallback_chain  # noqa: PLC0415

    providers = build_fallback_chain(settings)  # type: ignore[arg-type]
    max_retries = int(getattr(settings, "llm_max_retries", 2) or 0)
    return LLMChain(providers, max_retries=max_retries)
