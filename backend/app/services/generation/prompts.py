"""Prompt untuk generasi jawaban.

``SYSTEM_PROMPT`` dan ``NOT_FOUND_RESPONSE`` adalah bagian paling penting di
file ini. Keduanya mencegah halusinasi, dan keduanya bisa dirusak hanya dengan
satu kalimat yang terdengar sopan.
"""

from __future__ import annotations

from collections.abc import Sequence

from app.models.domain import Citation, RetrievedChunk

SYSTEM_PROMPT = """Kamu adalah asisten yang menjawab pertanyaan berdasarkan
dokumen yang diunggah pengguna.

Aturan yang wajib diikuti:

1. Gunakan HANYA informasi dari KONTEKS di bawah. Jangan memakai pengetahuan
   sendiri tentang topik itu, walaupun kamu merasa tahu.
2. Kalau konteks tidak memuat jawaban yang cukup, katakan dengan tegas bahwa
   informasi itu tidak ditemukan dalam dokumen. Itu jawaban yang benar dan
   diterima, bukan kegagalan.
3. Setiap klaim yang kamu buat harus bisa ditelusuri ke salah satu sumber yang
   diberi. Kalau tidak bisa, jangan diklaim.
4. Kalau dua sumber berbeda, sebutkan keduanya dan bedakan. Jangan pilih satu
   secara diam-diam.
5. Jawab dalam bahasa yang sama dengan bahasa pertanyaan pengguna.
6. Ringkas. Beberapa kalimat sudah cukup. Jangan mengulang kutipan utuh
   kecuali memang itu yang diminta.

Jangan menulis basa-basi seperti "Berdasarkan dokumen yang Anda unggah".
Langsung ke jawabannya."""

#: Dikirim kalau retrieval tidak menemukan yang cukup (FR-2.3). Perigten ini
#: dikirim SEBELUM memanggil LLM, jadi tidak ada panggilan model yang bisa
#: mengarang jawaban dari konteks kosong.
NOT_FOUND_RESPONSE = (
    "Informasi ini tidak ditemukan dalam dokumen yang diunggah. "
    "Coba dengan istilah yang dipakai di dalam dokumen, atau periksa daftar dokumen."
)


def build_context_prompt(
    question: str,
    retrieved: Sequence[RetrievedChunk],
    history: Sequence[tuple[str, str]],
    max_history: int,
) -> str:
    """Susun prompt untuk LLM.

    Args:
        question: Pertanyaan pengguna.
        retrieved: Chunk yang lolos retrieval, dari yang paling relevan.
        history: Pasangan ``(peran, isi)`` dari riwayat percakapan.
        max_history: Berapa pesan terakhir yang dipakai (FR-3.2).

    Returns:
        Prompt siap kirim, dengan konteks bernomor supaya model bisa menyebut
        sumbernya.
    """
    sections: list[str] = []

    if history:
        # Hanya pesan terakhir. Memakai seluruh riwayat membuat prompt
        # membengkak dan menghabiskan token tanpa menambah manfaat.
        recent = list(history)[-max_history:] if max_history > 0 else []
        if recent:
            lines = [f"- {role}: {content.strip()}" for role, content in recent]
            sections.append("RIWAYAT PERCAKAPAN SEBELUMNYA:\n" + "\n".join(lines))

    if retrieved:
        blocks: list[str] = []
        for index, item in enumerate(retrieved, start=1):
            location = (
                f"halaman {item.chunk.page_number}"
                if item.chunk.page_number is not None
                else f"chunk #{item.chunk.chunk_index + 1}"
            )
            blocks.append(
                f"[SUMBER {index}]\n"
                f"Dokumen: {item.document_name}\n"
                f"Lokasi: {location}\n"
                f"Skor kemiripan: {item.score:.3f}\n"
                f"Isi:\n{item.chunk.content}"
            )
        sections.append("KONTEKS DARI DOKUMEN:\n\n" + "\n\n".join(blocks))

    if not retrieved:
        # Pengaman kedua. Pemeriksaan utama ada di service, sebelum prompt ini
        # pernah dibangun.
        return f"{NOT_FOUND_RESPONSE}\n\nPertanyaan: {question}"

    context_block = "\n\n".join(sections)
    return (
        f"{context_block}\n\n"
        f"---\n"
        f"PERTANYAAN PENGGUNA: {question}\n\n"
        "Jawab hanya dari KONTEKS di atas. Sebutkan nomor sumber yang kamu pakai "
        "dengan format [SUMBER n]. Kalau konteksnya tidak cukup, katakan tidak "
        "ditemukan."
    )


def build_citations(retrieved: Sequence[RetrievedChunk]) -> list[Citation]:
    """Bentuk sitasi untuk dikirim ke frontend (FR-2.2).

    Cuplikan sengaja dipotong pendek: antarmuka sudah menyediakan tautan ke
    chunk penuh, jadi mengirim paragraf utuh hanya menambah payload tanpa
    menambah informasi.
    """
    return [
        Citation(
            document_id=item.chunk.document_id,
            document_name=item.document_name,
            page_number=item.chunk.page_number,
            chunk_index=item.chunk.chunk_index,
            excerpt=item.chunk.content[:220],
            score=item.score,
        )
        for item in retrieved
    ]
