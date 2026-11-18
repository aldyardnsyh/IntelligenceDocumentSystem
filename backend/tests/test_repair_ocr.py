"""Port dari pipeline eksternal (ids_upgrade): koreksi leksikon, perbaikan
penanda, catchword, dan meteran CER."""

from __future__ import annotations

from app.services.ingestion.cleanup import (
    build_corpus_lexicon,
    canon_form,
    correct_document_typos,
    repair_document_pages,
    repair_list_markers,
    restore_definition_markers,
)
from app.services.ingestion.ocr_engine import OcrLine, strip_catchwords
from scripts.eval_gold import error_rates, normalize


class TestCanonForm:
    def test_huruf_tertukar_dinormalkan(self) -> None:
        # c~e, l~i: "acara" yang salah baca jadi "aeara" bertemu kata aslinya.
        assert canon_form("acara") == canon_form("aeara")
        assert canon_form("rnal") == canon_form("mal")
        assert canon_form("clara") == canon_form("dara")

    def test_kapital_diabaikan(self) -> None:
        assert canon_form("Pengaduan") == canon_form("pengaduan")


class TestKoreksiLeksikon:
    def test_token_salah_baca_dikoreksi_dari_frekuensi(self) -> None:
        pages = [
            "pengaduan diterima oleh petugas yang telah tersertifikasi.",
            "pengaduan diterima oleh petugas yang telah tersertifikasi.",
            "pengaduan diterima oleh petugas yang telah tersertifikasi.",
            "pengaduan diterima oleh petugas yang telah tersertiflkasi.",  # l~i
        ]
        hasil = correct_document_typos(pages)
        assert "tersertifikasi" in hasil[3]
        # Halaman lain tidak berubah isinya.
        assert hasil[0] == pages[0]

    def test_kapital_asli_dipertahankan(self) -> None:
        # c→e pada "Secara" adalah substitusi yang kanoniknya bertabrakan;
        # koreksi harus tetap mempertahankan kapital aslinya.
        pages = [
            "Secara umum disediakan bagi masyarakat.",
            "Secara umum disediakan bagi masyarakat.",
            "Secara umum disediakan bagi masyarakat.",
            "Seeara umum disediakan bagi masyarakat.",
        ]
        hasil = correct_document_typos(pages)
        assert "Secara umum disediakan" in hasil[3]

    def test_kata_sah_langka_tidak_disentuh(self) -> None:
        # Kata di luar kamus yang kanoniknya TIDAK bertabrakan tetap utuh.
        pages = ["istilah khidmat Zarqowi muncul sekali saja pada pasal ini."]
        assert correct_document_typos(pages) == pages

    def test_token_berdigit_tidak_dikoreksi(self) -> None:
        pages = ["Nomor 2008 tentang ketentuan umum.", "ketentuan umum.", "ketentuan umum."]
        assert "Nomor 2008" in correct_document_typos(pages)[0]

    def test_korpus_sangat_pendek_tidak_mengubah_apapun(self) -> None:
        # Tidak ada kata ber-frekuensi >= 3: tidak ada kamus, tidak ada koreksi.
        pages = ["satu dua tiga."]
        assert correct_document_typos(pages) == pages


class TestBuildLeksikon:
    def test_frekuensi_minimum_dihormati(self) -> None:
        lexicon = build_corpus_lexicon(["pengaduan pengaduan", "pengaduan", "lain"])
        assert "pengaduan" in lexicon
        assert "lain" not in lexicon


class TestRepairListMarkers:
    def test_penanda_dua_huruf_dipulihkan_dari_urutan_abjad(self) -> None:
        tagged = [
            (0, "(1) Pengaduan disampaikan secara tertulis;"),
            (0, "a. melalui loket pengaduan;"),
            (0, "b. melalui pos elektronik;"),
            (0, "Cc. melalui panggilan telepon;"),
        ]
        hasil = dict(enumerate(repair_list_markers(tagged)))
        assert hasil[3][1].startswith("c. ")

    def test_penanda_tidak_dipulihkan_bila_abjadnya_tidak_cocok(self) -> None:
        # "Dd." setelah "b." bukan huruf berikutnya (harusnya "c."); biarkan.
        tagged = [
            (0, "(1) Pengaduan disampaikan secara tertulis;"),
            (0, "a. melalui loket;"),
            (0, "b. melalui pos;"),
            (0, "Dd. melalui telepon;"),
        ]
        hasil = dict(enumerate(repair_list_markers(tagged)))
        assert hasil[3][1].startswith("Dd. ")

    def test_tanda_baca_akhir_butir_dipulihkan(self) -> None:
        tagged = [
            (0, "(1) Pengelola wajib mencatat:"),
            (0, "a. identitas pengadu;"),
            (0, "b. isi pengaduan,"),
            (0, "c. bukti pendukung;"),
        ]
        hasil = dict(enumerate(repair_list_markers(tagged)))
        # "b." diakhiri "," tapi setelahnya ada butir "c." → pemisah antar
        # butir adalah titik koma, jadi "," salah baca dipulihkan.
        assert hasil[2][1].endswith(";")

    def test_akhir_ayat_dipulihkan_dari_nomor_ayat_berikutnya(self) -> None:
        tagged = [
            (0, "(1) Pengaduan diterima,"),
            (0, "(2) Pengaduan ditanggapi."),
        ]
        hasil = dict(enumerate(repair_list_markers(tagged)))
        assert hasil[0][1].endswith(".")


class TestRestoreDefinitionMarkers:
    def test_nomor_hilang_dipulihkan_berurutan(self) -> None:
        tagged = [
            (0, "Dalam Peraturan Presiden ini yang dimaksud dengan:"),
            (0, "1. Pelayanan publik adalah kegiatan pelayanan."),
            (0, ". Pengaduan adalah penyampaian."),
            (0, "3. Pengelola adalah unit kerja."),
        ]
        hasil = [text for _page, text in restore_definition_markers(tagged)]
        assert hasil[2].startswith("2. Pengaduan")

    def test_penanda_salah_baca_angka_dipulihkan(self) -> None:
        # "11." terbaca "Ii" oleh OCR.
        tagged = [
            (0, "Dalam Peraturan Presiden ini yang dimaksud dengan:"),
            (0, "1. Pelayanan publik."),
            (0, "Ii Pengaduan masyarakat."),
        ]
        hasil = [text for _page, text in restore_definition_markers(tagged)]
        assert hasil[2].startswith("2. Pengaduan")

    def test_di_luar_daftar_definisi_tidak_disentuh(self) -> None:
        tagged = [(0, "Pengelola menyediakan sarana."), (0, ". Baris aneh.")]
        assert restore_definition_markers(tagged) == tagged


class TestRepairDocumentPages:
    def test_daftar_lintas_halaman_dipulihkan(self) -> None:
        pages = [
            "Dalam Peraturan Presiden ini yang dimaksud dengan:\n"
            "1. Pelayanan publik adalah kegiatan.\n"
            "2. Pengaduan adalah penyampaian.\n",
            "3. Pengelola adalah unit kerja.\nPasal 2\nIsi pasal kedua.",
        ]
        hasil = repair_document_pages(pages, typo_correction=False)
        assert "3. Pengelola" in hasil[1]

    def test_baris_kosong_dan_paragraf_ikut_utuh(self) -> None:
        pages = ["Paragraf pertama.\n\nParagraf kedua."]
        hasil = repair_document_pages(pages, typo_correction=False)
        assert hasil[0] == pages[0]

    def test_koreksi_dan_perbaikan_jalan_berurutan(self) -> None:
        pages = [
            "Secara umum disediakan bagi masyarakat.",
            "Secara umum disediakan bagi masyarakat.",
            "Secara umum disediakan bagi masyarakat.",
            "a. sarana utama;\nSeeara langsung.\nBb. sarana pendukung,\nc. sarana lanjutan.",
        ]
        hasil = repair_document_pages(pages, typo_correction=True)
        # "Seeara" dikoreksi leksikon dulu (kapital dipertahankan), lalu
        # "Bb." dipulihkan menjadi "b." oleh perbaikan penanda.
        assert "Secara langsung." in hasil[3]
        assert "b. sarana pendukung;" in hasil[3]


def _line(text: str, x: float, y: float, width: float, height: float = 12.0) -> OcrLine:
    return OcrLine(text=text, confidence=0.9, x=x, y=y, width=width, height=height)


class TestStripCatchwords:
    def test_catchword_rata_kanan_dasar_halaman_dibuang(self) -> None:
        lines = [
            _line("(1) Setiap penyelenggara wajib menyediakan sarana", 60, 800, 500),
            _line("pengaduan yang mudah dijangkau masyarakat.", 60, 830, 460),
            _line("(2) Penyediaan", 620, 870, 60),
        ]
        hasil = strip_catchwords(lines)
        assert len(hasil) == 2
        assert all("(2)" not in line.text for line in hasil)

    def test_heading_di_dasar_halaman_tidak_dibuang(self) -> None:
        lines = [
            _line("Isi halaman penuh dengan teks yang panjang.", 60, 400, 500),
            _line("Pasal 7", 620, 870, 60),
        ]
        assert len(strip_catchwords(lines)) == 2

    def test_baris_pendek_di_kiri_tidak_dibuang(self) -> None:
        # Baris pendek di dasar tapi mulai dari kiri: kemungkinan akhir
        # paragraf biasa, bukan catchword.
        lines = [
            _line("Isi halaman penuh dengan teks yang panjang sekali.", 60, 400, 500),
            _line("publik.", 60, 870, 60),
        ]
        assert len(strip_catchwords(lines)) == 2


class TestMeteranCER:
    def test_teks_identik_nol(self) -> None:
        cer, wer = error_rates("Pengaduan diselesaikan 60 hari.", "Pengaduan diselesaikan 60 hari.")
        assert cer == 0.0 and wer == 0.0

    def test_satu_huruf_salah(self) -> None:
        cer, _ = error_rates("penyelenggara", "penyelenggaara")
        assert 0.0 < cer < 0.1

    def test_tanda_baca_dan_spasi_tidak_dihitung(self) -> None:
        cer, _ = error_rates("(1) Pengaduan, ditanggapi.", "1 Pengaduan ditanggapi")
        assert cer == 0.0

    def test_teks_kosong_aman(self) -> None:
        assert error_rates("", "apa pun") == (0.0, 0.0)

    def test_normalisasi_mengabaikan_kapital(self) -> None:
        assert normalize("Pengaduan Masyarakat") == normalize("pengaduan masyarakat")
