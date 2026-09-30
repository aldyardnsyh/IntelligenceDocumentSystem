"""Provider LLM yang berbasis API kompatibel OpenAI.

Ollama, SGLang, dan llama.cpp semuanya mengekspos endpoint OpenAI-compatible,
jadi satu implementasi ini menutup ketiganya. Groq punya implementasinya
sendiri di ``app.providers.groq`` karena ada perbedaan pada penanganan error
kuota.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from typing import Any

import httpx

from app.core.config import Settings
from app.providers.base import ProviderError

logger = logging.getLogger(__name__)


class OpenAICompatibleProvider:
    """Base untuk provider yang bicara protokol OpenAI ``/chat/completions``."""

    name = "openai-compatible"

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._base_url = ""
        self._model = ""
        self._api_key: str | None = None

    def is_configured(self) -> bool:
        """Provider lokal selalu terkonfigurasi: tidak butuh API key.

        Yang dicek adalah apakah servernya bisa dihubungi. Kalau tidak, saat
        pemanggilan pertama provider ini akan ditandai gagal dan rantai
        fallback lanjut ke provider berikutnya.
        """
        return True

    def _client(self, timeout: float) -> httpx.AsyncClient:
        headers: dict[str, str] = {"content-type": "application/json"}
        if self._api_key:
            headers["authorization"] = f"Bearer {self._api_key}"
        return httpx.AsyncClient(
            base_url=self._base_url,
            headers=headers,
            timeout=httpx.Timeout(timeout, connect=5.0),
        )

    def _payload(self, prompt: str, system: str | None, stream: bool) -> dict[str, Any]:
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

    @staticmethod
    def _classify(status_code: int) -> ProviderError:
        """Petakan status HTTP ke pesan yang bisa ditindaklanjuti."""
        if status_code == 429:
            return ProviderError(
                "Provider sedang membatasi laju permintaan.",
                retryable=True,
                status_code=status_code,
            )
        if status_code in (401, 403):
            return ProviderError(
                "Kredensial provider ditolak.",
                retryable=False,
                status_code=status_code,
            )
        if status_code == 404:
            return ProviderError(
                "Model tidak ditemukan di provider ini.",
                retryable=False,
                status_code=status_code,
            )
        if status_code >= 500:
            return ProviderError(
                "Provider mengalami gangguan internal.",
                retryable=True,
                status_code=status_code,
            )
        return ProviderError(
            f"Provider menolak permintaan (HTTP {status_code}).",
            retryable=False,
            status_code=status_code,
        )

    async def stream(self, prompt: str, system: str | None = None) -> AsyncIterator[str]:
        """Stream token dari ``/chat/completions`` dengan ``stream=true``."""
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
            raise ProviderError(
                "Provider tidak merespons dalam batas waktu.", retryable=True
            ) from exc
        except httpx.ConnectError as exc:
            # Server lokal belum jalan, atau base URL salah.
            raise ProviderError(
                f"Tidak bisa menghubungi {self.name} di {self._base_url}: {exc}",
                retryable=True,
            ) from exc
        except httpx.HTTPError as exc:
            raise ProviderError(
                f"Kesalahan jaringan pada {self.name}: {exc}",
                retryable=True,
            ) from exc

    async def complete(self, prompt: str, system: str | None = None) -> str:
        """Jawaban lengkap dalam satu panggilan."""
        payload = self._payload(prompt, system, stream=False)
        payload["stream"] = False

        try:
            async with self._client(self._settings.llm_timeout_seconds) as client:
                response = await client.post("/chat/completions", json=payload)
        except httpx.TimeoutException as exc:
            raise ProviderError(
                "Provider tidak merespons dalam batas waktu.", retryable=True
            ) from exc
        except httpx.ConnectError as exc:
            raise ProviderError(
                f"Tidak bisa menghubungi {self.name} di {self._base_url}: {exc}",
                retryable=True,
            ) from exc

        if response.status_code != 200:
            raise self._classify(response.status_code)
        return _extract_full_text(response.json())


class OllamaProvider(OpenAICompatibleProvider):
    """Ollama lokal.

    Default-nya backend MLX di Apple Silicon, atau llama.cpp di hardware lain.
    Untuk switching ke model lokal, cukup ``LLM_PROVIDER=ollama`` dan
    ``LLM_FALLBACK_CHAIN=groq``; Retrieval dan prompt tidak berubah.
    """

    name = "ollama"

    def __init__(self, settings: Settings) -> None:
        super().__init__(settings)
        self._base_url = settings.ollama_base_url.rstrip("/")
        self._model = settings.ollama_model


class SGLangProvider(OpenAICompatibleProvider):
    """SGLang.

    Dipilih kalau nanti trafik RAG-nya didominasi prefix yang sama (system
    prompt plus konteks retrieval yang identik), karena di bentuk beban itu
    prefix caching-nya memberi keuntungan di atas vLLM.
    """

    name = "sglang"

    def __init__(self, settings: Settings) -> None:
        super().__init__(settings)
        self._base_url = settings.sglang_base_url.rstrip("/")
        self._model = settings.sglang_model


def _extract_token(line: str) -> str:
    """Ambil teks dari satu baris SSE OpenAI-style.

    Mengembalikan string kosong untuk baris yang bukan data (``data:`` kosong,
    komentar ``:``, atau penanda akhir ``[DONE]``).
    """
    if not line.startswith("data:"):
        return ""
    payload = line[5:].strip()
    if not payload or payload == "[DONE]":
        return ""

    import json

    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        return ""
    return _delta_text(data)


def _delta_text(data: object) -> str:
    if not isinstance(data, dict):
        return ""
    choices = data.get("choices")
    if not isinstance(choices, list) or not choices:
        return ""
    first = choices[0]
    if not isinstance(first, dict):
        return ""
    delta = first.get("delta")
    if isinstance(delta, dict):
        content = delta.get("content")
        if isinstance(content, str):
            return content
    # Bentuk non-streaming (``complete``) memakai ``message`` atau ``text``.
    message = first.get("message")
    if isinstance(message, dict):
        content = message.get("content")
        if isinstance(content, str):
            return content
    text = first.get("text")
    return text if isinstance(text, str) else ""


def _extract_full_text(data: object) -> str:
    """Ambil seluruh teks dari respons JSON non-streaming."""
    if not isinstance(data, dict):
        return ""
    choices = data.get("choices")
    if not isinstance(choices, list) or not choices:
        return ""
    return _delta_text(data)
