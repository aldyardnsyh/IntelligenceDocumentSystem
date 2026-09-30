"""Generator jawaban dengan rantai fallback provider.

Tanggung jawab modul ini:

- Menjalankan model dengan prompt yang sudah terikat kutipan.
- Berpindah ke provider berikutnya kalau yang sekarang gagal secara retryable
  (kuota habis, provider tidak merespons).
- Mengembalikan jawaban lengkap *dan*(event token), supaya bisa dipakai untuk
  streaming maupun evaluasi batch.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass, field

from app.providers.base import LLMProvider, ProviderError
from app.services.generation.prompts import SYSTEM_PROMPT

logger = logging.getLogger(__name__)


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


class LLMChain:
    """Rantai provider dengan fallback otomatis.

    Konsepnya satu, provider-nya banyak. Kalau provider pertama gagal
    karena alasan yang sementara (429, timeout, server tidak hidup), provider
    berikutnya dicoba. Kalau gagalnya konfigurasi (API key salah), berhenti di
    situ, karena provider berikutnya punya masalah sendiri.
    """

    def __init__(self, providers: list[LLMProvider]) -> None:
        self._providers = [provider for provider in providers if provider.is_configured()]
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

    @property
    def provider_names(self) -> list[str]:
        return [provider.name for provider in self._providers]

    async def complete(self, prompt: str, system: str | None = SYSTEM_PROMPT) -> GenerationResult:
        """Jawaban lengkap, mencoba provider satu per satu."""
        attempts: list[str] = []
        last_error: ProviderError | None = None

        for index, provider in enumerate(self._providers):
            try:
                content = await provider.complete(prompt, system)
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
        dipakai, dan pemotongan dilaporkan sebagai penanda di akhir teks.
        """
        attempts: list[str] = []

        for provider in self._providers:
            emitted = False
            try:
                async for token in provider.stream(prompt, system):
                    emitted = True
                    yield token
            except ProviderError as exc:
                attempts.append(f"{provider.name}: {exc}")
                logger.warning("Provider %s gagal saat streaming: %s", provider.name, exc)
                if emitted:
                    # Sudah ada teks yang terkirim ke pengguna. Mengganti
                    # provider sekarang akan mengulang jawaban.
                    yield "\n\n[Provider bermasalah, jawaban mungkin terpotong.]"
                    return
                if not exc.retryable:
                    break
                continue

            if not emitted:
                attempts.append(f"{provider.name}: tidak ada token")
                continue
            return

        raise ProviderError("Semua provider gagal saat streaming. " + " | ".join(attempts))


def build_chain(settings: object) -> LLMChain:
    """Bangun rantai dari konfigurasi aplikasi."""
    from app.providers.base import build_fallback_chain  # noqa: PLC0415

    providers = build_fallback_chain(settings)  # type: ignore[arg-type]
    return LLMChain(providers)
