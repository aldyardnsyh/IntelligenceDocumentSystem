"""Test chunking struktur hukum.

Dokumen uji disusun meniru anatomi peraturan resmi: pembukaan (Menimbang/
Mengingat), BAB, Bagian, Pasal dengan ayat dan butir, Pasal yang melintasi
halaman, dan blok penetapan di akhir. Yang diuji bukan sekadar "ada chunk",
tapi konteks yang menempel di tiap chunk — karena itulah yang membuat jawaban
dapat disitasi ke Pasal yang benar.
"""

from __future__ import annotations

import pytest

from app.services.ingestion.legal import build_legal_chunks, legal_structure_summary

LEGAL_DOC = """PERATURAN UJI NOMOR 1 TAHUN 2024
TENTANG PENGELOLAAN PENGADUAN UJI

PRESIDEN REPUBLIK INDONESIA,
Menimbang:
a. bahwa untuk pengujian perlu menetapkan peraturan tentang pengelolaan pengaduan;
b. bahwa berdasarkan pertimbangan sebagaimana dimaksud dalam huruf a,
perlu menetapkan Peraturan Uji;
Mengingat:
1. Pasal 4 ayat (1) Undang-Undang Dasar Negara Republik Indonesia Tahun 1945;
2. Undang-Undang Nomor 25 Tahun 2009 tentang Pelayanan Publik;
MEMUTUSKAN:
Menetapkan: PERATURAN UJI TENTANG PENGELOLAAN PENGADUAN UJI.

BAB I
KETENTAN UMUM

Pasal 1
Dalam Peraturan ini yang dimaksud dengan:
1. Pelayanan publik adalah kegiatan atau rangkaian kegiatan untuk melayani
masyarakat sesuai dengan peraturan perundang-undangan.
2. Pengaduan adalah penyampaian keluhan atas pelayanan yang tidak sesuai dengan standar pelayanan.
3. Pengelola adalah pejabat yang ditugaskan untuk mengelola pengaduan masyarakat.

Bagian Kedua
Sarana Pengaduan

Pasal 2
(1) Setiap penyelenggara wajib menyediakan sarana pengaduan untuk
mengelola pengaduan pelayanan publik.
(2) Penyediaan sarana pengaduan sebagaimana dimaksud pada ayat (1)
memperhatikan kepentingan kelompok rentan atau berkebutuhan khusus.

Pasal 3
Pada setiap sarana pengaduan harus tersedia informasi tentang mekanisme
tata cara pengaduan yang mudah diperoleh dan dipahami oleh penerima
pelayanan.

BAB II
PENUTUP

Pasal 4
Peraturan Uji ini mulai berlaku pada tanggal diundangkan.

Ditetapkan di Jakarta pada tanggal 1 Januari 2024. Peraturan ini diumumkan
dengan penempatannya dalam Lembaran Negara Republik Indonesia, dan salinan
asli dokumen ini disimpan oleh Sekretariat Negara Republik Indonesia
sebagai arsip resmi negara yang ditandatangani oleh Presiden Republik
Indonesia.
"""


class TestParseStruktur:
    def test_setiap_pasal_menjadi_chunk(self) -> None:
        spans = build_legal_chunks(LEGAL_DOC, max_chars=900)
        sections = [span.section for span in spans]
        assert "Pasal 1" in sections
        assert "Pasal 2" in sections
        assert "Pasal 3" in sections
        assert "Pasal 4" in sections
        assert sections.count("Pasal 1") == 1

    def test_header_membawa_konteks_bab_dan_bagian(self) -> None:
        spans = build_legal_chunks(LEGAL_DOC, max_chars=900)
        pasal_1 = next(span for span in spans if span.section == "Pasal 1")
        # Pasal 1 berada sebelum "Bagian Kedua", jadi header-nya tidak boleh
        # menyebut Bagian Kedua — konteks mengikuti posisi di dokumen.
        assert "BAB I" in pasal_1.content
        assert "Pasal 1" in pasal_1.content
        assert "KETENTAN UMUM" in pasal_1.content
        assert "Bagian Kedua" not in pasal_1.content.split("\n\n")[0]

        pasal_2 = next(span for span in spans if span.section == "Pasal 2")
        header = pasal_2.content.split("\n\n")[0]
        assert "BAB I" in header
        assert "Bagian Kedua" in header
        assert "Sarana Pengaduan" in header

    def test_isi_pasal_utuh_dan_tanpa_pasal_lain(self) -> None:
        spans = build_legal_chunks(LEGAL_DOC, max_chars=900)
        pasal_2 = next(span for span in spans if span.section == "Pasal 2")
        assert "menyediakan sarana pengaduan" in pasal_2.content
        assert "kelompok rentan" in pasal_2.content
        # Teks Pasal 3 tidak boleh bocor ke chunk Pasal 2.
        assert "Pasal 3" not in pasal_2.content

    def test_preamble_menjadi_chunk(self) -> None:
        spans = build_legal_chunks(LEGAL_DOC, max_chars=900)
        preamble = [span for span in spans if span.section == "Pembukaan"]
        assert preamble
        assert "Menimbang" in preamble[0].content
        assert "MENGINGAT".lower() in preamble[0].content.lower()

    def test_penutup_menjadi_chunk(self) -> None:
        spans = build_legal_chunks(LEGAL_DOC, max_chars=900)
        closing = [span for span in spans if span.section == "Penetapan"]
        assert closing
        assert "Ditetapkan di Jakarta" in closing[0].content

    def test_pasal_lintas_halaman_tetap_satu_chunk(self) -> None:
        # Pasal 2 sengaja dipotong: halaman 1 berakhir tepat di tengah isinya.
        doc = LEGAL_DOC.replace("Pasal 2\n(1)", "Pasal 2\n\f(1)")
        spans = build_legal_chunks(doc, max_chars=900)
        pasal_2 = [span for span in spans if span.section == "Pasal 2"]
        assert len(pasal_2) == 1
        assert "menyediakan sarana pengaduan" in pasal_2[0].content

    def test_pasal_lintas_halaman_mencatat_halaman_awal(self) -> None:
        doc = LEGAL_DOC.replace("Pasal 2\n(1)", "Pasal 2\n\f(1)")
        spans = build_legal_chunks(doc, max_chars=900)
        pasal_2 = next(span for span in spans if span.section == "Pasal 2")
        assert pasal_2.page_number == 1


class TestPemecahanPasalPanjang:
    def test_pasal_panjang_dipecah_di_batas_ayat(self) -> None:
        ayat = (
            "(1) Setiap penyelenggara wajib menyediakan sarana pengaduan yang "
            "dilengkapi petugas pengelola kompeten dan berlokasi di tempat yang "
            "mudah dijangkau masyarakat untuk menerima pengaduan secara langsung "
            "maupun tidak langsung tanpa pungutan biaya."
        )
        doc = (
            "Pasal 1\n"
            + "\n".join([ayat] * 3)
            + "\n(2) Ketentuan lanjut mengikuti.\n"
            + "Pasal 2\nIsi pasal kedua.\n"
        )
        spans = build_legal_chunks(doc, max_chars=300)
        pasal_1 = [span for span in spans if span.section == "Pasal 1"]
        assert len(pasal_1) > 1
        # Tiap pecahan membawa header konteks yang sama.
        assert all(span.content.startswith("Pasal 1") for span in pasal_1)

    def test_pasal_butir_numerik_dipecah(self) -> None:
        butir = "\n".join(
            f"{i}. Pengelolaan pengaduan nomor {i} dilaksanakan dengan cermat "
            "sesuai mekanisme dan tata cara pengelolaan pengaduan pelayanan publik."
            for i in range(1, 8)
        )
        doc = "Pasal 1\nDalam Peraturan ini yang dimaksud dengan:\n" + butir + "\nPasal 2\nIsi.\n"
        spans = build_legal_chunks(doc, max_chars=300)
        pasal_1 = [span for span in spans if span.section == "Pasal 1"]
        assert len(pasal_1) > 1


class TestFallback:
    def test_teks_non_legal_mengembalikan_kosong(self) -> None:
        assert build_legal_chunks("Catatan biasa tanpa struktur pasal sama sekali.", 500) == []

    def test_satu_pasal_saja_mengembalikan_kosong(self) -> None:
        # Kurang dari dua heading: terlalu mudah salah deteksi, lebih aman
        # menyerahkan ke chunking paragraf generik.
        doc = "Pasal 1\nIsi tunggal tanpa pasal lain yang mengikutinya."
        assert build_legal_chunks(doc, 500) == []

    def test_max_chars_tidak_valid_ditolak(self) -> None:
        with pytest.raises(ValueError):
            build_legal_chunks(LEGAL_DOC, 0)

    def test_ringkasan_struktur(self) -> None:
        spans = build_legal_chunks(LEGAL_DOC, 900)
        ringkasan = legal_structure_summary(spans)
        assert "4 pasal" in ringkasan
