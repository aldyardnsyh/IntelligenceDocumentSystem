"""Provider Groq (API cloud, free tier).

Bedanya dengan ``OpenAICompatibleProvider`` ada pada penanganan rate limit.
Groq free tier punya empat plafon yang berlomba: request/menit,
request/hari, token/menit, dan token/hari. Yang biasanya mengikat lebih dulu
adalah token harian, bukan jumlah request, jadi pesan errornya harus
menyebutkan itu supaya developer tahu harus mengurangi usage, bukan membuat
API key baru.

Catatan: batas Groq berlaku per organisasi, bukan per API key.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator

import httpx

from app.core.config import Settings
from app.providers.base import ProviderError
from app.providers.openai_compatible import _extract_full_text, _extract_token

logger = logging.getLogger(__name__)


class GroqProvider:
    """GroqCloud lewat protokol OpenAI-compatible."""

    name = "groq"

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._api_key = settings.groq_api_key
        self._base_url = settings.groq_base_url.rstrip("/")
        self._model = settings.llm_model

    def is_configured(self) -> bool:
        """Groq butuh API key. Tanpa itu, provider ini dilewati diam-diam."""
        return bool(self._api_key)

    def _client(self, timeout: float) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=self._base_url,
            headers={
                "authorization": f"Bearer {self._api_key}",
                "content-type": "application/json",
            },
            timeout=httpx.Timeout(timeout, connect=5.0),
        )

    def _payload(self, prompt: str, system: str | None, stream: bool) -> dict[str, object]:
        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        return {
            "model": self._model,
            "messages": messages,
            "temperature": self._settings.llm_temperature,
            "max_tokens": self._settings.llm_max_tokens,
            "stream": stream,
        }

    def _classify(self, status_code: int) -> ProviderError:
        if status_code == 429:
            return ProviderError(
                "Groq free tier sudah mencapai batas harian. "
                "Batas ini berlaku per organisasi dan tidak bertambah dengan API key baru. "
                "Rantai fallback akan mencoba provider berikutnya.",
                retryable=True,
                status_code=429,
            )
        if status_code in (401, 403):
            return ProviderError(
                "GROQ_API_KEY ditolak oleh Groq.",
                retryable=False,
                status_code=status_code,
            )
        if status_code == 404:
            return ProviderError(
                f"Model '{self._model}' tidak tersedia di Groq. "
                "Cek daftar model di konsol Groq.",
                retryable=False,
                status_code=404,
            )
        if status_code >= 500:
            return ProviderError(
                "Groq mengalami gangguan.",
                retryable=True,
                status_code=status_code,
            )
        return ProviderError(
            f"Groq menolak permintaan (HTTP {status_code}).",
            retryable=False,
            status_code=status_code,
        )

    async def stream(self, prompt: str, system: str | None = None) -> AsyncIterator[str]:
        payload = self._payload(prompt, system, stream=True)
        try:
            async with (
                self._client(self._settings.llm_timeout_seconds) as client,
                client.post("/chat/completions", json=payload) as response,
            ):
                if response.status_code != 200:
                    raise self._classify(response.status_code)
                async for line in response.aiter_lines():
                    token = _extract_token(line)
                    if token:
                        yield token
        except httpx.TimeoutException as exc:
            raise ProviderError("Groq tidak merespons dalam batas waktu.", retryable=True) from exc
        except httpx.HTTPError as exc:
            raise ProviderError(f"Kesalahan jaringan ke Groq: {exc}", retryable=True) from exc

    async def complete(self, prompt: str, system: str | None = None) -> str:
        payload = self._payload(prompt, system, stream=False)
        try:
            async with self._client(self._settings.llm_timeout_seconds) as client:
                response = await client.post("/chat/completions", json=payload)
        except httpx.TimeoutException as exc:
            raise ProviderError("Groq tidak merespons dalam batas waktu.", retryable=True) from exc
        except httpx.HTTPError as exc:
            raise ProviderError(f"Kesalahan jaringan ke Groq: {exc}", retryable=True) from exc

        if response.status_code != 200:
            raise self._classify(response.status_code)
        return _extract_full_text(response.json())
