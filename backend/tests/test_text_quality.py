"""Test penilaian kualitas text-layer dan pembersihan teks.

Fixture utamanya adalah potongan nyata text-layer PDF Perpres 76/2013 (Lembaran
Negara dari BPK): urutan bacanya kacau, kata-katanya terpecah ("Undang-Undan g",
"Tah un"), dan dipenuhi artefak kaki halaman. Dokumen seperti ini lolos
pemeriksaan "tidak kosong" dan dulu diindeks apa adanya — keputusan needs_ocr
harus menangkapnya, sementara teks bersih tidak boleh salah terdeteksi.
"""

from __future__ import annotations

from app.services.ingestion.cleanup import clean_page_text, is_noise_line
from app.services.ingestion.parser import ParsedPage
from app.services.ingestion.text_quality import assess_text_layer

#: Potongan text-layer rusak, disalin dari ekstraksi pypdf halaman 1-3 PDF
#: Perpres 76/2013. Karakter rusaknya dipertahankan apa adanya.
GARBLED_PAGE = """tclah ...
2. Undang-Undan g Nomor 32 Tah un 2004 tentang
Pemerin tah an Daerah (Lembaran Negara Rcpublik
Indonesia Tahun 2004 Nomor 125, Tamb ahan Lembaran
Negara Republik Indon esia Nomor 4437) sebagaiman a
L
1. Pasal 4 ayat (1) Undang-Undang Dasar Negara Repu blik
Indones ia Tahun 1945;
a. bahwa sesuai dengan ketentuan Pa sal 36 dan
Pasal 37 Undang-Undang Nomor 25 Tahun 2009 tentang
Pelayanan Publik diwajibkan bagi penye lenggara
pelayanan publik untuk men yediakan sarana pengadu an
dan menu gaskan Pelaksana yang kompeten dalam
pengelolaan peng aduan ;
b. bah wa pembentukan sarana pengaduan dan penugasan
kepada pengelola pengaduan pelayanan publik
bertu juan untuk memenuhi kebu tuhan masyarakat
dalam mempe r oleh pelayanan publik yang berkualitas
, wajar , dan adil;"""

CLEAN_LEGAL_PAGE = """Pasal 12
(1) Pengaduan dapat dilakukan oleh setiap orang yang dirugikan atau pihak lain
yang menerima kuasa untuk mewakilinya.
(2) Pengaduan sebagaimana dimaksud pada ayat (1) dilakukan paling lambat 30
(tiga puluh) hari sejak pengadu menerima layanan.
(3) Penyelenggara wajib menyelesaikan setiap pengaduan paling lambat 60
(enam puluh) hari sejak berkas pengaduan dinyatakan lengkap."""


class TestCleanup:
    def test_baris_nomor_halaman_dibuang(self) -> None:
        # Tiga bentuk nomor halaman yang muncul di Lembaran Negara hasil pindai.
        assert is_noise_line("\\ 2 -")
        assert is_noise_line("- 12 -")
        assert is_noise_line("14")

    def test_cap_gazette_varian_rusak_dibuang(self) -> None:
        # Variasi salah baca OCR atas "PRESIDEN REPUBLIK INDONESIA" yang
        # benar-benar muncul di text-layer PDF BPK.
        assert is_noise_line("PRESIDEN REP UBL IK INDONESIA")
        assert is_noise_line("PRE SI OEN REPUBLIK INOONESIA")
        assert is_noise_line("PRES I DEN REPUBLIK INDONESIA")

    def test_penanda_margin_ellipsis_dibuang(self) -> None:
        assert is_noise_line("f dalam ...")
        assert is_noise_line("Pengelola ...")

    def test_isi_dokumen_tidak_dibuang(self) -> None:
        assert not is_noise_line("Pengelola pengaduan pelayanan publik wajib melapor.")
        assert not is_noise_line("Pasal 12")
        assert not is_noise_line("b. bahwa pembentukan sarana pengaduan;")
        assert not is_noise_line("")

    def test_clean_page_text_mempertahankan_isi(self) -> None:
        text = "\n".join(
            [
                "Pasal 12",
                "(3) Penyelenggara wajib menyelesaikan setiap pengaduan.",
                "\\ 3 -",
                "PRES I DEN REPUBLIK INOONESIA",
                "Penyelenggara wajib melakukan pemantauan dan evaluasi ...",
            ]
        )
        cleaned = clean_page_text(text)
        assert "Pasal 12" in cleaned
        assert "(3) Penyelenggara" in cleaned
        assert "\\ 3 -" not in cleaned
        assert "PRES I DEN" not in cleaned
        assert "pemantauan dan evaluasi" not in cleaned


class TestAssessTextLayer:
    def test_text_layer_rusak_memicu_ocr(self) -> None:
        pages = [
            ParsedPage(text=GARBLED_PAGE, page_number=1),
            ParsedPage(text=GARBLED_PAGE, page_number=2),
        ]
        report = assess_text_layer(pages)
        assert report.needs_ocr is True
        assert report.reasons
        assert report.single_char_token_ratio > 0.05

    def test_teks_bersih_tidak_memicu_ocr(self) -> None:
        pages = [ParsedPage(text=CLEAN_LEGAL_PAGE, page_number=i + 1) for i in range(3)]
        report = assess_text_layer(pages)
        assert report.needs_ocr is False
        assert report.reasons == []

    def test_halaman_kosong_memicu_ocr(self) -> None:
        pages = [
            ParsedPage(text="", page_number=1),
            ParsedPage(text="", page_number=2),
            ParsedPage(text=CLEAN_LEGAL_PAGE, page_number=3),
        ]
        report = assess_text_layer(pages)
        assert report.needs_ocr is True
        assert report.empty_page_ratio > 0.2
        assert "kosong" in report.reasons[0]

    def test_butir_huruf_pada_satu_halaman_tidak_memicu_ocr(self) -> None:
        # Halaman padat butir "a."-"f." sah: rasio satu hurufnya tinggi di
        # halaman itu, tapi agregat level dokumen harus tetap di bawah ambang.
        butir = "\n".join(
            f"{huruf}. Penyelenggara wajib melakukan pencatatan dan pelaporan "
            "pengelolaan pengaduan sesuai dengan ketentuan peraturan perundang-undangan;"
            for huruf in "abcdef"
        )
        pages = [
            ParsedPage(text=butir, page_number=1),
            ParsedPage(text=CLEAN_LEGAL_PAGE, page_number=2),
            ParsedPage(text=CLEAN_LEGAL_PAGE, page_number=3),
        ]
        report = assess_text_layer(pages)
        assert report.needs_ocr is False

    def test_reasons_dapat_dibaca(self) -> None:
        pages = [ParsedPage(text=GARBLED_PAGE, page_number=1)]
        report = assess_text_layer(pages)
        # Alasan keputusan ditulis untuk log operator, bukan boolean telanjang.
        assert all("rasio" in reason or "kosong" in reason for reason in report.reasons)
