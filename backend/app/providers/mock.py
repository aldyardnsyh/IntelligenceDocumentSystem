"""Provider tanpa LLM, untuk mode demo dan test.

Jawaban disusun secara ekstraktif dari chunk yang benar-benar lolos retrieval.
Ini **bukan** LLM dan tidak berpura-pura jadi LLM: kalimat penutup pada
responsnya menyebutkan hal itu, supaya kalau demo ini dipakai untuk
presentasi, yang terlihat memang batasan nyata, bukan hasil sintetis.

Memakai provider ini membuat seluruh pipeline bisa diuji tanpa API key,
lolos jaringan, atau menunggu antrean. Itu yang membuat test integrasi
menjadi mungkin dilakukan.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

from app.core.config import Settings

#: Kutipan yang dipratinjau sebagai "sumber" supaya Citation Card punya isi.
EXCERPT_LIMIT = 220


class MockProvider:
    """Provider deterministik yang menyalin kutipan chunk."""

    name = "mock"

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def is_configured(self) -> bool:
        return True

    async def stream(self, prompt: str, system: str | None = None) -> AsyncIterator[str]:
        # Prompt dari generator selalu diawali marker sumber. Kalau tidak ada,
        # berarti pemanggil mengirim langsung, dan jawabannya jujur.
        for token in self._render(prompt):
            await asyncio.sleep(0.01)
            yield token

    async def complete(self, prompt: str, system: str | None = None) -> str:
        return "".join(self._render(prompt))

    @staticmethod
    def _render(prompt: str) -> list[str]:
        """Pecah kutipan menjadi potongan pendek supaya efek streaming terlihat."""
        lines = [line for line in prompt.strip().split("\n") if line.strip()]
        if not lines:
            return ["Tidak ada konteks yang tersedia."]

        output: list[str] = []
        for index, line in enumerate(lines):
            if index == 0:
                output.append("Kutipan langsung dari dokumen:\n\n")
            output.append(line.strip())
            output.append("\n" if index < len(lines) - 1 else "")
        output.append(
            "\n\nMode demo: jawaban ini disusun dengan menyalin kutipan, "
            "bukan sintesis LLM. Backend sungguhan akan menggantinya dengan "
            "generasi LLM yang tetap terikat pada kutipan yang sama."
        )

        # Dipotong per beberapa karakter supaya consumer streaming benar-benar
        # menerima potongan, bukan satu string panjang.
        joined = "".join(output)
        return [joined[index : index + 6] for index in range(0, len(joined), 6)]
