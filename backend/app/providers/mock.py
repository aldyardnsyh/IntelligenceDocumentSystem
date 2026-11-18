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

#: Hasil OCR contoh untuk ``complete_vision``. Strukturnya meniru dokumen
#: hukum sungguhan (BAB, Pasal, ayat) supaya test integrasi yang menyambung
#: mock OCR ke chunking legal bisa menguji seluruh jalurnya.
MOCK_OCR_TEXT = """BAB I
KETENTUAN UMUM

Pasal 1
Dalam Peraturan Presiden ini yang dimaksud dengan:
1. Pelayanan publik adalah kegiatan atau rangkaian kegiatan dalam rangka
pemenuhan kebutuhan pelayanan bagi setiap warga negara dan penduduk atas
barang, jasa, dan/atau pelayanan administratif yang disediakan oleh
penyelenggara pelayanan publik.
2. Pengaduan adalah penyampaian keluhan yang disampaikan pengadu kepada
pengelola pengaduan pelayanan publik atas pelayanan pelaksana yang tidak
sesuai dengan standar pelayanan.

Pasal 2
(1) Setiap penyelenggara wajib menyediakan sarana pengaduan untuk mengelola
pengaduan pelayanan publik.
(2) Penyediaan sarana pengaduan sebagaimana dimaksud pada ayat (1)
memperhatikan kepentingan kelompok rentan atau berkebutuhan khusus."""


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

    async def complete(
        self, prompt: str, system: str | None = None, *, model: str | None = None
    ) -> str:
        # ``model`` diterima demi kompatibilitas tanda tangan dengan provider
        # sungguhan, lalu diabaikan: mock tidak punya katalog model.
        del model
        return "".join(self._render(prompt))

    async def complete_vision(
        self, prompt: str, images: list[bytes], system: str | None = None
    ) -> str:
        """Teks contoh deterministik untuk jalur OCR tanpa jaringan.

        Provider mock tidak punya mata, jadi ia tidak bisa benar-benar
        membaca gambar. Yang penting untuk pengujian adalah kontraknya:
        teks terstruktur kembali per halaman, dan pipeline di atasnya bisa
        diuji tanpa API key. Teks contoh sengaja berbentuk struktur hukum
        supaya chunking legal ikut terpicu saat test integrasi.
        """
        if not images:
            raise ValueError("complete_vision butuh setidaknya satu gambar.")
        return MOCK_OCR_TEXT

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
