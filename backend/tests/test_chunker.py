"""Test chunker.

Fokusnya bukan "apakah menghasilkan N chunk", tapi apakah batas chunk jatuh di
tempat yang masuk akal dan apakah tidak ada teks yang hilang.
"""

from __future__ import annotations

import pytest

from app.services.ingestion.chunker import chunk_text, normalize_text


class TestNormalizeText:
    def test_menggabungkan_carriage_return(self) -> None:
        assert normalize_text("baris1\r\nbaris2") == "baris1\nbaris2"

    def test_merapikan_spasi_berlebih(self) -> None:
        assert normalize_text("a     b") == "a b"

    def test_membatasi_newline_bertumpuk(self) -> None:
        assert normalize_text("a\n\n\n\n\nb") == "a\n\nb"

    def test_teks_kosong_setelah_normalisasi(self) -> None:
        assert normalize_text("   \n\n  ") == ""


class TestChunkText:
    def test_teks_kosong_tidak_menghasilkan_chunk(self) -> None:
        assert chunk_text("", 500, 50) == []

    def test_teks_kecil_menjadi_satu_chunk(self) -> None:
        chunks = chunk_text("Paragraf pendek.", 500, 50)
        assert len(chunks) == 1
        assert chunks[0].content == "Paragraf pendek."

    def test_memotong_pada_batas_paragraf(self) -> None:
        text = "\n\n".join(f"Paragraf nomor {index}. " + "x" * 200 for index in range(5))
        chunks = chunk_text(text, 500, 50)
        assert len(chunks) > 1
        # Setiap chunk harus utas: tidak ada yang terpotong di tengah kata.
        for chunk in chunks:
            assert chunk.content.strip()

    def test_heading_markdown_jadi_chunk_tersendiri(self) -> None:
        text = "Paragraf pembuka yang cukup panjang untuk diuji. " * 10 + "\n\n## Judul Bagian"
        chunks = chunk_text(text, 500, 50)
        assert any(chunk.content.startswith("## ") for chunk in chunks)

    def test_overlap_membawa_ekor_ke_chunk_berikutnya(self) -> None:
        text = "Kalimat pertama yang panjang sekali. " * 20
        chunks = chunk_text(text, 300, 50)
        assert len(chunks) > 1
        # Ekor chunk pertama harus muncul di awal chunk kedua.
        tail = chunks[0].content[-30:]
        assert tail[:15] in chunks[1].content

    def test_posisi_karakter_konsisten_dengan_isi(self) -> None:
        text = "Baris pertama.\n\nBaris kedua yang lebih panjang untuk diuji. " * 5
        for chunk in chunk_text(text, 400, 40):
            # Offset harus menunjuk ke substring yang benar-benar cocok.
            assert text[chunk.char_start : chunk.char_start + 10] == chunk.content[:10]

    def test_offset_samad_panjang_soal_kutipan(self) -> None:
        """``text[char_start:char_end]`` harus persis sama dengan content.

        Offset meleset di sini tidak merusak retrieval, tapi merusak sitasi:
        Citation Card menyorot potongan yang berbeda dari jawaban yang
        diberikan model, jadi sumbernya tidak bisa diverifikasi.

        Offset merujuk teks yang sudah dinormalisasi, itu teks yang benar-benar
        dipecah, jadi perbandingannya juga harus memakai teks itu.
        """
        raw = (
            "Kalimat pertama yang panjang sekali untuk dipotong.\n" * 6
            + "\n\nParagraf kedua dengan isi berbeda. " * 6
        )
        text = normalize_text(raw)
        for chunk in chunk_text(raw, 200, 30):
            assert text[chunk.char_start : chunk.char_end] == chunk.content

    def test_tidak_mengarang_spasi_antar_kalimat(self) -> None:
        # Baris baru di dalam paragraf harus tetap baris baru di chunk, bukan
        # diganti spasi saat kalimat dirakit ulang.
        raw = "Kalimat pertama.\nKalimat kedua.\n\nParagraf berikutnya. " * 8
        text = normalize_text(raw)
        for chunk in chunk_text(raw, 120, 20):
            assert chunk.content in text

    def test_estimasi_token_positif(self) -> None:
        chunks = chunk_text("Teks pendek.", 500, 50)
        assert chunks[0].token_estimate() >= 1

    def test_menolak_size_nol(self) -> None:
        with pytest.raises(ValueError, match="size"):
            chunk_text("teks", 0, 0)

    def test_menolak_overlap_yang_melebihi_size(self) -> None:
        with pytest.raises(ValueError, match="overlap"):
            chunk_text("teks", 100, 100)

    def test_menolak_overlap_negatif(self) -> None:
        with pytest.raises(ValueError, match="overlap"):
            chunk_text("teks", 100, -1)

    def test_kalimat_panjang_dipotong_tetapi_tidak_hilang(self) -> None:
        # Satu kalimat tanpa titik yang jauh lebih panjang dari size.
        long_sentence = "kata " * 400
        chunks = chunk_text(long_sentence, 200, 20)
        assert len(chunks) > 1
        # Semua potongan harus berisi kata dari kalimat asli.
        for chunk in chunks:
            assert all(word == "kata" for word in chunk.content.split())

    def test_batas_ukuran_dihormati_setelah_kalimat_pendek(self) -> None:
        # Jalur ini pernah dilewati: kalimat pendek mengisi buffer, lalu
        # kalimat raksasa dianggap "tidak muat" tapi tidak pernah dipotong
        # karakter karena buffer dianggap sudah dikuras.
        text = "Kalimat pendek. " + ("kata tanpa titik " * 200)
        for chunk in chunk_text(text, 500, 50):
            assert len(chunk.content) <= 500

    def test_semua_chunk_dalam_batas(self) -> None:
        text = ("Kalimat normal. " * 50) + ("tanpa titik " * 300)
        for size, overlap in ((500, 50), (200, 20), (120, 0)):
            for chunk in chunk_text(text, size, overlap):
                assert len(chunk.content) <= size
