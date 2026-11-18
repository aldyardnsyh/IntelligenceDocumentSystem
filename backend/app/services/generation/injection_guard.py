"""Penyaring anti-prompt-injection dengan classifier llama-prompt-guard.

Aturan di SYSTEM_PROMPT (rasul 14-16) bertahan di level model, tapi bertahan
di level model artinya masih bergantung pada model untuk menuruti aturan.
Classifier ``meta-llama/llama-prompt-guard-2-86m`` menambah lapisan di luar
model generasi: setiap konten yang akan masuk prompt dinilai lebih dulu, dan
yang terdeteksi membawa instruksi diblokir sebelum pernah sampai ke LLM.

Model ini mengembalikan satu angka probabilitas (0..1) sebagai isi respons,
bukan teks biasa. Konteks dipotong 1.800 karakter karena classifier punya
window 512 token; instruksi terselubung praktis selalu berada di awal chunk
yang disisipkan orang, bukan di paragraf ke-40 dokumen sah.

Fail-open dengan sengaja: classifier yang gagal atau mengembalikan bentuk tak
dikenal tidak menjatuhkan jawaban, ia hanya membuat chunk itu lolos tanpa
penilaian. Sistem yang menjawab lebih diutamakan daripada sistem yang menolak
semua karena alat pemeriksaannya mati.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from app.providers.base import LLMProvider

if TYPE_CHECKING:
    from app.core.config import Settings

logger = logging.getLogger(__name__)

#: Batas karakter per teks yang dikirim ke classifier. Window model 512 token;
#: teks legal Indonesia ~4 karakter per token, jadi 1.800 karakter aman.
_MAX_SCREEN_CHARS = 1_800


class InjectionGuard:
    """Penilai risiko injection untuk konten yang akan masuk prompt."""

    def __init__(self, provider: LLMProvider, model: str, threshold: float) -> None:
        self._provider = provider
        self._model = model
        self.threshold = threshold

    @property
    def model_name(self) -> str:
        return self._model

    async def screen(self, texts: list[str]) -> list[float | None]:
        """Nilai risiko setiap teks, paralel; None berarti tidak bisa dinilai.

        Urutan hasil sama dengan urutan masukan, supaya pemanggil bisa
        memetakan skor ke chunk tanpa penebakan.
        """
        if not texts:
            return []
        return list(
            await asyncio.gather(
                *(self.screen_one(text) for text in texts),
                return_exceptions=False,
            )
        )

    async def screen_one(self, text: str) -> float | None:
        """Skor risiko satu teks (0..1), atau None kalau tidak bisa dinilai."""
        try:
            raw = await self._provider.complete(
                text[:_MAX_SCREEN_CHARS], model=self._model
            )
        except Exception:  # noqa: BLE001
            # Fail-open: kegagalan classifier bukan alasan menjatuhkan jawaban.
            logger.debug("Prompt guard gagal menilai konten", exc_info=True)
            return None
        return _parse_score(raw)


def _parse_score(raw: str) -> float | None:
    """Baca skor probabilitas dari isi respons classifier.

    Model mengembalikan satu angka sebagai teks ("0.9994..."). Respons yang
    bukan angka (mis. provider mock yang menyalin kutipan) berarti pemanggil
    tidak bisa dinilai dan diperlakukan sebagai None, bukan nol: nol berarti
    "dipastikan aman", sedangkan None berarti "tidak dinilai".
    """
    try:
        value = float(raw.strip().strip("\"'"))
    except (TypeError, ValueError):
        return None
    if 0.0 <= value <= 1.0:
        return value
    return None


def build_injection_guard(
    settings: Settings, provider: LLMProvider | None
) -> InjectionGuard | None:
    """Bangun guard dari konfigurasi, atau None kalau tidak layak dipakai."""
    if not settings.prompt_guard_enabled or provider is None:
        return None
    if not provider.is_configured():
        logger.info(
            "Prompt guard dimatikan: provider %s tidak siap. Konten tidak "
            "disaring classifier; bertahan hanya pada aturan prompt.",
            provider.name,
        )
        return None
    return InjectionGuard(
        provider, settings.prompt_guard_model, settings.prompt_guard_threshold
    )
