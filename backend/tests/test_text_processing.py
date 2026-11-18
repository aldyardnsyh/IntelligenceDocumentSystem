"""Test pemrosesan teks Indonesia untuk BM25.

Stemming Sastrawi adalah fitur recall: "pengaduan", "mengadu", dan "diadukan"
harus bertemu di bentuk dasar yang sama, dan itu berlaku SERAGAM untuk
dokumen maupun query. Tokenisasi tanpa stemming (mode test) juga diuji supaya
perilaku default test tetap deterministik dan cepat.
"""

from __future__ import annotations

import pytest

from app.services.retrieval.text_processing import (
    configure_stemming,
    keyword_suggestions,
    stem_word,
    tokenize_for_search,
)


@pytest.fixture
def stemming_on() -> None:
    configure_stemming(
        type("S", (), {"bm25_stemming_enabled": True})()  # type: ignore[arg-type]
    )
    yield
    configure_stemming(
        type("S", (), {"bm25_stemming_enabled": False})()  # type: ignore[arg-type]
    )


class TestTokenize:
    def test_tanpa_stemming_stabil(self) -> None:
        configure_stemming(
            type("S", (), {"bm25_stemming_enabled": False})()  # type: ignore[arg-type]
        )
        # "tentang" ada di daftar stopword: kata penghubung, bukan isi.
        assert tokenize_for_search("Pengaduan tentang Pelayanan!") == [
            "pengaduan",
            "pelayanan",
        ]

    def test_angka_dipertahankan(self) -> None:
        configure_stemming(
            type("S", (), {"bm25_stemming_enabled": False})()  # type: ignore[arg-type]
        )
        assert "60" in tokenize_for_search("paling lambat 60 hari")
        assert "2013" in tokenize_for_search("Perpres 2013")

    def test_stopword_dan_huruf_tunggal_dibuang(self) -> None:
        configure_stemming(
            type("S", (), {"bm25_stemming_enabled": False})()  # type: ignore[arg-type]
        )
        tokens = tokenize_for_search("yang oleh b a z")
        assert "yang" not in tokens
        assert "oleh" not in tokens
        assert "a" not in tokens
        assert "z" not in tokens


class TestStemming:
    def test_bentuk_turunan_bertemu_di_dasar(self, stemming_on: None) -> None:
        # Ini inti manfaatnya: tiga bentuk yang dipakai dokumen dan pertanyaan
        # bermuara ke token yang sama.
        assert stem_word("pengaduan") == stem_word("mengadu") == stem_word("diadukan")
        assert stem_word("penyelenggara") == "selenggara"

    def test_tokenize_menggunakan_stemmer(self, stemming_on: None) -> None:
        assert "adu" in tokenize_for_search("pengaduan masyarakat")

    def test_angka_tidak_distem(self, stemming_on: None) -> None:
        # Stemmer tidak boleh menyentuh angka: "2013" tetap "2013".
        assert "2013" in tokenize_for_search("tahun 2013")


class TestKeywordSuggestions:
    def test_kata_isi_terambil_urut(self) -> None:
        assert keyword_suggestions("Berapa batas waktu penyelesaian pengaduan?") == (
            "batas",
            "waktu",
            "penyelesaian",
            "pengaduan",
        )

    def test_stopword_dan_angka_dibuang(self) -> None:
        assert keyword_suggestions("apa itu pasal 12?") == ("pasal",)

    def test_pertanyaan_kosong_isi(self) -> None:
        assert keyword_suggestions("yang yang yang") == ()
