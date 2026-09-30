"""Antarmuka provider LLM.

Provider di-abstract sebagai protocol, bukan base class, supaya test bisa
memakai stub tanpa harus mengimplementasikan async yang tidak terpakai.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from typing import Protocol, runtime_checkable

from app.core.config import Settings

logger = logging.getLogger(__name__)


def _registry() -> dict[str, type]:
    """Peta nama provider ke kelasnya.

    Import dilakukan di dalam fungsi supaya modul ini tidak menarik dependensi
    provider apa pun saat baru diimpor.
    """
    from app.providers.groq import GroqProvider
    from app.providers.mock import MockProvider
    from app.providers.openai_compatible import OllamaProvider, SGLangProvider

    return {
        "groq": GroqProvider,
        "ollama": OllamaProvider,
        "sglang": SGLangProvider,
        "mock": MockProvider,
    }


class ProviderError(RuntimeError):
    """Kegagalan saat memanggil provider.

    ``retryable`` menentukan apakah rantai fallback harus mencoba provider
    berikutnya. 429 (kuota habis) retryable, karena itu memang kondisi
    sementara. 401 (API key salah) tidak retryable: provider berikutnya punya
    key sendiri, dan mencoba lagi hanya menambah lambat.
    """

    def __init__(
        self,
        message: str,
        *,
        retryable: bool = False,
        status_code: int | None = None,
    ) -> None:
        super().__init__(message)
        self.retryable = retryable
        self.status_code = status_code


@runtime_checkable
class LLMProvider(Protocol):
    """Satu provider generation teks.

    Semua provider lokal dan cloud mengekspos API kompatibel OpenAI, jadi
    implementasi ini bisa dipakai ulang oleh Groq, Ollama, dan SGLang. Yang
    membedakan hanya base URL, model, dan API key.
    """

    name: str

    def is_configured(self) -> bool:
        """True kalau provider siap dipakai.

        Provider tanpa API key tidak akan dicoba; rantai fallback berjalan di
        bawahnya.
        """
        ...

    async def stream(self, prompt: str, system: str | None = None) -> AsyncIterator[str]:
        """Stream token per token.

        Provider yang tidak mendukung streaming harus meng-*yield* seluruh
        jawaban sebagai satu chunk, supaya antarmuka ini sama untuk semua.
        """
        ...


def build_provider(settings: Settings) -> LLMProvider:
    """Bangun provider aktif sesuai ``LLM_PROVIDER``."""
    provider_cls = _registry().get(settings.llm_provider)
    if provider_cls is None:
        raise ValueError(f"LLM_PROVIDER tidak dikenal: {settings.llm_provider}")
    return provider_cls(settings)  # type: ignore[return-value]


def build_fallback_chain(settings: Settings) -> list[LLMProvider]:
    """Bangun semua provider yang akan dicoba, sesuai urutan konfigurasi.

    Nama yang tidak dikenal **melempar error**, bukan dilewati diam-diam.
    Versi sebelumnya memakai ``if provider_cls is not None``, yang membuat
    salah ketik seperti ``LLM_FALLBACK_CHAIN=groqq`` hanya diam-diam
    membuang provider: rantai tetap berjalan, jawaban tetap muncul, dan tidak
    ada yang realised bahwa provider yang dimaksud tidak pernah dipanggil.
    """
    registry = _registry()
    chain: list[LLMProvider] = []
    for name in settings.effective_fallback_chain:
        provider_cls = registry.get(name)
        if provider_cls is None:
            raise ValueError(
                f"Provider fallback tidak dikenal: {name}. "
                f"Pilihan yang tersedia: {', '.join(sorted(registry))}."
            )
        chain.append(provider_cls(settings))  # type: ignore[arg-type]
    return chain
