"""Test penilai offline untuk RAGAS.

Mode offline ada karena jalur RAGAS sebelumnya tidak pernah dijalankan di CI:
butuh API key dan berbiaya. Akibatnya lima bug berbeda hanya terlihat saat
seseorang membayar token, termasuk skor yang selalu kosong karena pembacaan
hasil memakai API yang salah.

Test di sini tidak membutuhkan RAGAS terpasang. Yang diuji adalah bagian yang
bisa diuji tanpa paket itu: pembacaan skema dari prompt, penyusunan JSON yang
memenuhi skema, dan determinisme embedding. Jalur RAGAS penuh diuji terpisah
dengan venv yang memasang RAGAS.
"""

from __future__ import annotations

import json

import pytest

from app.services.evaluation_evaluator import (
    OfflineEvaluator,
    _blok_input,
    _isi_skema,
    _potong_balasan,
    _skema_dari_prompt,
    kesamaan_kata,
)


class TestBacaSkema:
    def test_skema_diambil_dari_prompt(self) -> None:
        prompt = (
            "Nilai sesuatu.\n"
            'Please return the output in a JSON format that complies with the '
            'following schema as specified in JSON Schema:\n'
            '{"properties": {"reason": {"type": "string"}, '
            '"verdict": {"type": "integer"}}, '
            '"required": ["reason", "verdict"], "type": "object"}'
            "Do not use single quotes."
        )
        skema = _skema_dari_prompt(prompt)
        assert skema is not None
        assert set(skema["properties"]) == {"reason", "verdict"}

    def test_tanpa_skema_mengembalikan_none(self) -> None:
        assert _skema_dari_prompt("prompt biasa tanpa skema") is None

    def test_objek_bersarang_terbaca_utuh(self) -> None:
        prompt = (
            "JSON Schema:\n"
            '{"properties": {"a": {"type": "object", "properties": '
            '{"b": {"type": "string"}}}}, "type": "object"}'
        )
        skema = _skema_dari_prompt(prompt)
        assert skema is not None
        assert skema["properties"]["a"]["properties"]["b"]["type"] == "string"


class TestIsiSkema:
    def test_verdict_berisi_satu(self) -> None:
        skema = {
            "properties": {"reason": {"type": "string"}, "verdict": {"type": "integer"}},
            "type": "object",
        }
        hasil = _isi_skema(skema, "input: {}", skema)
        assert hasil["verdict"] == 1
        assert isinstance(hasil["reason"], str)

    def test_noncommittal_berisi_nol(self) -> None:
        """`noncommittal` punya arti berlawanan dari `verdict`.

        Nilai 1 membuat RAGAS menganggap semua jawaban mengelak, dan skor
        answer relevancy jatuh ke 0 tanpa alasan yang terlihat.
        """
        skema = {
            "properties": {
                "question": {"type": "string"},
                "noncommittal": {"type": "integer"},
            },
            "type": "object",
        }
        hasil = _isi_skema(skema, "input: {}", skema)
        assert hasil["noncommittal"] == 0

    def test_rujukan_def_diikuti(self) -> None:
        """Pydantic menulis model bersarang sebagai $ref ke $defs.

        Tanpa mengikuti rujukan itu, tipe item array terbaca kosong dan diisi
        string, lalu faithfulness mengembalikan NaN.
        """
        skema = {
            "properties": {"statements": {"type": "array", "items": {"$ref": "#/$defs/S"}}},
            "$defs": {
                "S": {
                    "type": "object",
                    "properties": {
                        "statement": {"type": "string"},
                        "reason": {"type": "string"},
                        "verdict": {"type": "integer"},
                    },
                }
            },
            "type": "object",
        }
        hasil = _isi_skema(skema, "input: {}", skema)
        assert isinstance(hasil["statements"], list)
        assert hasil["statements"], "daftar kosong membuat RAGAS mengembalikan NaN"
        assert set(hasil["statements"][0]) == {"statement", "reason", "verdict"}
        assert hasil["statements"][0]["verdict"] == 1


class TestBacaInput:
    def test_blok_input_diambil_dari_akhir_prompt(self) -> None:
        prompt = (
            "Instruksi panjang di awal yang tidak boleh terbaca.\n"
            "Now perform the same with the following input\n"
            'input: {"question": "Berapa lama?", "response": "Dua hari."}\n'
            "Output: "
        )
        assert _blok_input(prompt) == {"question": "Berapa lama?", "response": "Dua hari."}

    def test_nilai_diambil_dari_input_bukan_instruksi(self) -> None:
        """Ini bug yang membuat answer relevancy selalu 0.

        Kolom `question` sempat terisi teks instruksi, bukan pertanyaan, dan
        skornya terlihat seperti "jawaban tidak relevan".
        """
        prompt = (
            "Generate a question for the given answer. Give noncommittal as 1.\n"
            "input: {\n  \"response\": \"Batas penyelesaian dua hari kerja.\"\n}\n"
            "Output: "
        )
        assert "Batas penyelesaian" in _potong_balasan(prompt)
        assert "Generate a question" not in _potong_balasan(prompt)


class TestEmbeddingDanDeterminisme:
    def test_embedding_stabil(self) -> None:
        evaluator = OfflineEvaluator()
        assert evaluator.embed_query("dua hari kerja") == evaluator.embed_query(
            "dua hari kerja"
        )

    def test_embedding_membedakan_teks(self) -> None:
        evaluator = OfflineEvaluator()
        assert evaluator.embed_query("dua hari") != evaluator.embed_query("tiga jam")

    def test_embedding_ternormalisasi(self) -> None:
        evaluator = OfflineEvaluator()
        vektor = evaluator.embed_query("batas penyelesaian permintaan")
        panjang = sum(nilai * nilai for nilai in vektor) ** 0.5
        assert panjang == pytest.approx(1.0)

    def test_balasan_berupa_json_valid(self) -> None:
        evaluator = OfflineEvaluator()
        prompt = (
            "JSON Schema:\n"
            '{"properties": {"verdict": {"type": "integer"}}, "type": "object"}'
        )
        hasil = evaluator.generate_text(prompt)
        teks = hasil.generations[0][0].text
        assert json.loads(teks)["verdict"] == 1

    def test_antarmuka_yang_dituntut_ragas_ada(self) -> None:
        """RAGAS menuntut beberapa method yang tidak jelas dari dokumentasi.

        Kelimanya ditemukan lewat kegagalan berturut-turut saat pipa dijalankan
        sungguhan. Test ini mengunci keberadaannya supaya tidak terhapus saat
        refactor, karena menghapus salah satunya hanya membuat skor kosong.
        """
        evaluator = OfflineEvaluator()
        for nama in (
            "set_run_config",
            "generate_text",
            "agenerate_text",
            "generate",
            "agenerate",
            "get_temperature",
            "is_finished",
            "embed_query",
            "embed_documents",
            "aembed_query",
            "aembed_documents",
        ):
            assert hasattr(evaluator, nama), f"method {nama} hilang"


class TestKesamaanKata:
    def test_sempurna(self) -> None:
        assert kesamaan_kata("batas dua hari kerja", "dua hari kerja") == 1.0

    def test_tidak_ada(self) -> None:
        assert kesamaan_kata("pemasangan server", "dua hari kerja") == 0.0

    def test_target_kosong(self) -> None:
        assert kesamaan_kata("apa saja", "") == 0.0
