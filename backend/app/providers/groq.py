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

import base64
import logging
from collections.abc import AsyncIterator

import httpx

from app.core.config import Settings
from app.providers.base import ProviderError
from app.providers.openai_compatible import (
    _extract_full_text,
    _extract_token,
    _retry_after_seconds,
)

logger = logging.getLogger(__name__)


class GroqProvider:
    """GroqCloud lewat protokol OpenAI-compatible."""

    name = "groq"

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._api_key = settings.groq_api_key
        self._base_url = settings.groq_base_url.rstrip("/")
        # ``GROQ_MODEL`` menimpa ``LLM_MODEL``: katalog model Groq berbeda
        # dari katalog provider primary (mis. endpoint OpenAI-compatible
        # dengan katalog berbeda), dan rantai fallback butuh nama model yang
        # benar-benar ada di masing-masing.
        self._model = settings.groq_model or settings.llm_model
        self._shared: httpx.AsyncClient | None = None

    def is_configured(self) -> bool:
        """Groq butuh API key. Tanpa itu, provider ini dilewati diam-diam.

        Key yang hanya berisi spasi dihitung tidak ada juga: kalau lolos,
        request berikutnya mati di httpx dengan "Illegal header value" — pesan
        yang tidak menyebut penyebabnya sama sekali.
        """
        return bool(self._api_key and self._api_key.strip())

    async def _shared_client(self, timeout: float) -> httpx.AsyncClient:
        """Klien HTTP yang dipakai bersama antar request.

        Membuat klien baru tiap panggilan berarti handshake TLS baru tiap
        kali. Pada free tier, biaya itu tidak kecil, dan tidak ada alasan
        teknis untuk tidak memakai koneksi yang sama.
        """
        if self._shared is None:
            self._shared = httpx.AsyncClient(
                base_url=self._base_url,
                headers={
                    "authorization": f"Bearer {self._api_key}",
                    "content-type": "application/json",
                },
                timeout=httpx.Timeout(timeout, connect=5.0),
            )
        return self._shared

    async def aclose(self) -> None:
        """Tutup klien bersama. Dipanggil saat shutdown aplikasi."""
        if self._shared is not None:
            await self._shared.aclose()
            self._shared = None

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

    def _classify(self, status_code: int, retry_after: float | None = None) -> ProviderError:
        if status_code == 429:
            # 429 dari Groq bisa berarti batas per menit (RPM/TPM) atau batas
            # harian. Menyebut "batas harian" untuk keduanya membuat operator
            # salah mendiagnosis; indikator retry-after dibawa apa adanya dari provider.
            detail = "atas permintaan provider" if retry_after else "atas kuota"
            return ProviderError(
                f"Groq membatasi laju permintaan, {detail}. "
                "Rantai fallback akan mencoba provider berikutnya.",
                retryable=True,
                status_code=429,
                retry_after_seconds=retry_after,
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
            client = await self._shared_client(self._settings.llm_timeout_seconds)
            # Klien bersama tidak boleh dipakai sebagai async context manager:
            # keluar dari `async with` menutupnya, lalu pemakaian berikutnya
            # melempar RuntimeError "Cannot reopen a client instance", yang
            # artinya pertanyaan pertama berhasil dan semua berikutnya gagal.
            # Yang ditutup di sini hanya objek respons.
            response = await client.send(
                client.build_request("POST", "/chat/completions", json=payload),
                stream=True,
            )
            try:
                if response.status_code != 200:
                    raise self._classify(
                        response.status_code, _retry_after_seconds(response)
                    )
                async for line in response.aiter_lines():
                    token = _extract_token(line)
                    if token:
                        yield token
            finally:
                await response.aclose()
        except httpx.TimeoutException as exc:
            raise ProviderError("Groq tidak merespons dalam batas waktu.", retryable=True) from exc
        except httpx.HTTPError as exc:
            raise ProviderError(f"Kesalahan jaringan ke Groq: {exc}", retryable=True) from exc

    async def complete(
        self, prompt: str, system: str | None = None, *, model: str | None = None
    ) -> str:
        """Jawaban lengkap dalam satu panggilan, dengan opsi timpa model.

        ``model`` dipakai layanan khusus (mis. classifier prompt-guard) yang
        berbagi kredensial dan klien dengan generation tapi butuh model lain.
        """
        payload = self._payload(prompt, system, stream=False)
        if model:
            payload["model"] = model
        try:
            client = await self._shared_client(self._settings.llm_timeout_seconds)
            response = await client.post("/chat/completions", json=payload)
        except httpx.TimeoutException as exc:
            raise ProviderError("Groq tidak merespons dalam batas waktu.", retryable=True) from exc
        except httpx.HTTPError as exc:
            raise ProviderError(f"Kesalahan jaringan ke Groq: {exc}", retryable=True) from exc

        if response.status_code != 200:
            raise self._classify(response.status_code, _retry_after_seconds(response))
        return _extract_full_text(response.json())

    async def complete_vision(
        self, prompt: str, images: list[bytes], system: str | None = None
    ) -> str:
        """OCR halaman scan lewat model vision Groq.

        Format multimodal Groq mengikuti protokol OpenAI: gambar sebagai
        ``image_url`` data-URI di dalam konten user. Model dan parameternya
        dibaca dari setting vision, bukan setting chat, karena kebutuhan
        keduanya berbeda (OCR butuh temperatur 0 dan output panjang).
        """
        if not images:
            raise ValueError("complete_vision butuh setidaknya satu gambar.")

        content: list[dict[str, object]] = [{"type": "text", "text": prompt}]
        for image in images:
            encoded = base64.b64encode(image).decode("ascii")
            content.append(
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/png;base64,{encoded}"},
                }
            )

        messages: list[dict[str, object]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": content})
        payload: dict[str, object] = {
            "model": self._settings.vision_model,
            "messages": messages,
            "temperature": self._settings.vision_temperature,
            "max_tokens": self._settings.vision_max_tokens,
            "stream": False,
        }

        try:
            client = await self._shared_client(self._settings.vision_timeout_seconds)
            response = await client.post("/chat/completions", json=payload)
        except httpx.TimeoutException as exc:
            raise ProviderError(
                "Groq vision tidak merespons dalam batas waktu.", retryable=True
            ) from exc
        except httpx.HTTPError as exc:
            raise ProviderError(f"Kesalahan jaringan ke Groq: {exc}", retryable=True) from exc

        if response.status_code != 200:
            raise self._classify(response.status_code, _retry_after_seconds(response))
        return _extract_full_text(response.json())
