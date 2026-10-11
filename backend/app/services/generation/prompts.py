"""Prompt untuk generasi jawaban.

``SYSTEM_PROMPT`` dan ``NOT_FOUND_RESPONSE`` adalah bagian paling penting di
file ini. Keduanya mencegah halusinasi, dan keduanya bisa dirusak hanya dengan
satu kalimat yang terdengar sopan.
"""

from __future__ import annotations

from collections.abc import Sequence

from app.models.domain import Citation, RetrievedChunk

SYSTEM_PROMPT = """Kamu adalah asisten dokumen yang menjawab pertanyaan
pengguna secara profesional, informatif, dan mengalir seperti sedang
berdiskusi, bukan seperti mesin yang menempel kutipan.

Aturan isi:

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

Aturan gaya, ini yang membedakan jawaban asisten dari salinan dokumen:

6. **Tulis ulang dengan kalimatmu sendiri.** Jangan menyalin potongan konteks
   apa adanya. Susun ulang menjadi kalimat yang mengalir dan enak dibaca.
7. **Jangan menampilkan markup mentah.** Buang penanda seperti `**tebal**`,
   `#` judul, `-` daftar, `|` tabel, atau garis `====` dari jawaban. Kalau
   isinya berupa daftar, sampaikan sebagai kalimat bernomor yang rapi atau
   daftar bertanda yang bersih, tanpa simbol mentah dari dokumen.
8. **Rangkai, jangan mengulang.** Kalau pertanyaannya meminta ringkasan,
   padukan isi beberapa sumber menjadi satu penjelasan; jangan menumpuk
   kutipan berurutan.
9. Ringkas dan langsung ke intinya. Beberapa kalimat biasanya cukup. Sebut
   nomor sumber hanya di akhir klaim yang memang perlu ditelusuri, dengan
   format [SUMBER n], jangan menaruh penanda itu di setiap kalimat.
10. Nada bicara: tenang, membantu, dan percaya diri. Boleh memakai kalimat
    pengantar singkat yang natural kalau membantu, tapi jangan basa-basi
    seperti "Berdasarkan dokumen yang Anda unggah".

Aturan tanda baca:

11. Jangan memakai em dash atau en dash. Pakai koma, titik, titik dua, atau
    tanda kurung sesuai kebutuhan kalimat.
12. Jangan memakai tanda hubung ganda sebagai pengganti tanda pisah.
13. Jangan memakai tanda hubung untuk menyambung klausa. Tanda hubung hanya
    untuk kata ulang dan kata majemuk seperti "dua hari kerja"."""

#: Dikirim kalau retrieval tidak menemukan yang cukup. Perigten ini
#: dikirim SEBELUM memanggil LLM, jadi tidak ada panggilan model yang bisa
#: mengarang jawaban dari konteks kosong.
NOT_FOUND_RESPONSE = (
    "Informasi ini tidak ditemukan dalam dokumen yang diunggah. "
    "Coba dengan istilah yang dipakai di dalam dokumen, atau periksa daftar dokumen."
)

UNGROUNDED_SYSTEM_PROMPT = """Kamu adalah asisten yang menjawab pertanyaan
pengguna. Untuk pertanyaan ini TIDAK ADA konteks dari dokumen pengguna, jadi
kamu menjawab dari pengetahuan umummu.

Aturan yang wajib diikuti:

1. Jawab pertanyaannya dengan sungguh-sungguh. Jangan menolak, jangan
   menjawab "informasi tidak ditemukan dalam dokumen", dan jangan berpura-pura
   tidak tahu kalau kamu memang tahu.
2. Jangan pernah mengklaim jawaban ini berasal dari dokumen pengguna, dan
   jangan menyebut nomor sumber atau kutipan. Dokumennya tidak dipakai di sini.
3. Kalau pengetahuanmu tidak mencakup hal yang ditanyakan (misalnya harga atau
   kejadian yang berubah-ubah), katakan bagian mana yang tidak kamu ketahui,
   lalu berikan apa yang kamu tahu tentang topiknya. Jangan mengarang angka
   atau fakta spesifik.
4. Kalau pertanyaannya ambigu, jawab tafsir yang paling masuk akal dan sebut
   tafsir itu.
5. Jawab dalam bahasa yang sama dengan bahasa pertanyaan pengguna.
6. Ringkas dan langsung. Tanpa basa-basi pembuka.
7. Jangan memakai em dash atau en dash. Pakai koma, titik, atau tanda
   kurung. Jangan memakai tanda hubung ganda sebagai pengganti tanda pisah,
   dan jangan memakai tanda hubung untuk menyambung klausa.

Larangan yang paling penting, jangan dilanggar:

8. **Jangan menyusun daftar pustaka, daftar buku, daftar artikel, atau daftar
   tautan.** Kamu tidak punya katalog yang bisa diverifikasi, jadi apa pun
   yang kamu sebutkan akan mengarang judul, penulis, tahun, penerbit, atau
   URL. Itu lebih buruk daripada tidak menjawab, karena terlihat kredibel dan
   tidak bisa dicek pengguna.
9. **Jangan menyebut URL apa pun.** Alamat yang kamu ingat bisa sudah berubah,
   salah, atau tidak pernah ada.
10. **Jangan menyebut angka spesifik yang bisa berubah** seperti harga, tanggal
    kejadian, jumlah, atau nomor versi, kecuali kamu yakin itu fakta umum yang
    stabil. Kalau tidak yakin, sebutkan bahwa angkanya perlu dicek.
11. Kalau yang diminta adalah daftar referensi atau dokumen, katakan terus
    terang bahwa kamu tidak bisa menyediakannya dari ingatan, lalu sarankan
    mencari di katalog resmi atau meminta dokumen itu diunggah ke aplikasi
    ini supaya bisa ditanyai."""


def build_ungrounded_prompt(
    question: str,
    history: Sequence[tuple[str, str]],
    max_history: int,
) -> str:
    """Prompt untuk mode "jawab tanpa dokumen".

    Dipisah dari ``build_context_prompt`` karena kontraknya berbeda: yang ini
    memang meminta model memakai pengetahuan umumnya, dengan syarat tidak
    mengklaim bersumber pada dokumen. Memakai prompt berbasis kutipan di sini
    membuat model menjawab "tidak ditemukan", persis kegagalan yang mode ini
    ada untuk mencegahnya.
    """
    sections: list[str] = []
    recent = list(history)[-max_history:] if max_history > 0 else []
    if recent:
        lines = [f"- {role}: {content.strip()}" for role, content in recent]
        sections.append("RIWAYAT PERCAKAPAN SEBELUMNYA:\n" + "\n".join(lines))

    sections.append(
        "Tidak ada konteks dokumen untuk pertanyaan ini. Jawab dari "
        "pengetahuan umummu, tanpa mengklaim bersumber pada dokumen."
    )
    return "\n\n".join(sections) + f"\n\nPERTANYAAN PENGGUNA: {question}"


def build_context_prompt(
    question: str,
    retrieved: Sequence[RetrievedChunk],
    history: Sequence[tuple[str, str]],
    max_history: int,
    *,
    allow_history_only: bool = False,
) -> str:
    """Susun prompt untuk LLM.

    Args:
        question: Pertanyaan pengguna.
        retrieved: Chunk yang lolos retrieval, dari yang paling relevan.
        history: Pasangan ``(peran, isi)`` dari riwayat percakapan.
        max_history: Berapa pesan terakhir yang dipakai.
        allow_history_only: Izinkan menjawab dari riwayat saja saat tidak ada
            chunk yang lolos. Dipakai untuk pertanyaan lanjutan ("berapa
            lama?" setelah "berapa hari SLA?") yang jawabannya sudah ada di
            percakapan sebelumnya. Tanpa ini, prompt mengembalikan pesan
            "tidak ditemukan" dan jalur riwayat tidak pernah bekerja.

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
        # pernah dibangun. Kecuali pemanggil menyatakan bahwa riwayat boleh
        # jadi satu-satunya sumber.
        if not allow_history_only or not sections:
            return f"{NOT_FOUND_RESPONSE}\n\nPertanyaan: {question}"
        return (
            f"{chr(10).join(sections)}\n\n"
            f"---\n"
            f"PERTANYAAN PENGGUNA: {question}\n\n"
            "Retrieval tidak menemukan potongan dokumen baru untuk pertanyaan "
            "ini. Jawab berdasarkan RIWAYAT PERCAKAPAN di atas, karena di "
            "sanalah jawaban itu sudah pernah disebut. Kalau riwayatnya pun "
            "tidak memuat jawabannya, katakan tidak ditemukan. Jangan memakai "
            "pengetahuan umum."
        )

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
    """Bentuk sitasi untuk dikirim ke frontend.

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
