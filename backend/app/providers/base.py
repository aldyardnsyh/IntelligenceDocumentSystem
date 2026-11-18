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
    from app.providers.openai_compatible import (
        OllamaProvider,
        OpenAICompatibleEndpointProvider,
        SGLangProvider,
    )

    return {
        "groq": GroqProvider,
        "openai_compatible": OpenAICompatibleEndpointProvider,
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

    ``retry_after_seconds`` diisi dari header ``Retry-After`` kalau provider
    mengirimkannya, sehingga rantai bisa menunggu tepat sebanyak yang diminta
    server, bukan menebak dengan backoff buta.
    """

    def __init__(
        self,
        message: str,
        *,
        retryable: bool = False,
        status_code: int | None = None,
        retry_after_seconds: float | None = None,
    ) -> None:
        super().__init__(message)
        self.retryable = retryable
        self.status_code = status_code
        self.retry_after_seconds = retry_after_seconds


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
    _guard_mock(settings, settings.llm_provider)
    return provider_cls(settings)  # type: ignore[return-value]


def _guard_mock(settings: Settings, provider_name: str) -> None:
    """Peringatan keras kalau provider mock dipakai di luar mode dev.

    Provider mock menyalin cuplikan dokumen, bukan sintesis. Dari luar ia
    terlihat identik: health ``ok``, jawaban muncul, sitasi lengkap. Yang
    berbeda baru terasa saat kualitasnya diukur, jadi sistem harus tetap
    boot, tapi operator harus diberi tahu lewat log dan health, bukan lewat
    crash loop yang membuat masalah sebenarnya tidak terlihat.
    """
    if provider_name != "mock" or settings.debug:
        return
    logger.error(
        "LLM_PROVIDER=mock dipakai saat DEBUG=false: jawaban yang muncul "
        "adalah cuplikan dokumen, bukan sintesis LLM. Health akan melaporkan "
        "mode reduced. Set LLM_PROVIDER=groq atau ollama untuk produksi."
    )


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
    for provider in chain:
        _guard_mock(settings, provider.name)
    return chain


def build_vision_provider(settings: Settings) -> LLMProvider:
    """Provider untuk OCR halaman scan (``VISION_PROVIDER``).

    Registry-nya sengaja sama dengan provider generation: Groq, Ollama, dan
    SGLang semuanya mengekspos multimodal lewat protokol OpenAI-compatible,
    jadi kelas yang sama bisa dipakai. Yang membedakan hanyalah model dan
    parameternya, yang dibaca dari setting vision saat ``complete_vision``
    dipanggil.
    """
    provider_cls = _registry().get(settings.vision_provider)
    if provider_cls is None:
        raise ValueError(
            f"VISION_PROVIDER tidak dikenal: {settings.vision_provider}. "
            f"Pilihan yang tersedia: {', '.join(sorted(_registry()))}."
        )
    _guard_mock(settings, settings.vision_provider)
    return provider_cls(settings)  # type: ignore[return-value]


def vision_provider_ready(settings: Settings) -> bool:
    """True kalau provider vision bisa dipanggil sekarang.

    Dipakai parser untuk memutuskan apakah PDF hasil pindai boleh dilanjutkan
    ke OCR, atau harus ditolak dengan pesan yang bisa ditindaklanjuti. Error
    apa pun saat pengecekan berarti "tidak siap": pelaporan kegagalan ingestion
    yang jelas lebih berguna daripada crash di jalur pemeriksaan itu sendiri.
    """
    try:
        return build_vision_provider(settings).is_configured()
    except Exception:  # noqa: BLE001
        return False
