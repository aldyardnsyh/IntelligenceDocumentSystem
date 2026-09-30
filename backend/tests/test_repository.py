"""Test repository SQLite.

Fokus pada perilaku yang mudah salah: pagination, penghitungan ``total``
setelah filter, dan pengacakan judul sesi tanpa menyentuh ``last_active_at``.
"""

from __future__ import annotations

import pytest

from app.models.domain import (
    ChatSession,
    Chunk,
    Document,
    DocumentStatus,
    QueryLog,
)
from app.repositories.sqlite_repo import SqliteRepository, new_id, utc_now


def make_document(**overrides: object) -> Document:
    defaults: dict[str, object] = {
        "id": new_id("doc"),
        "filename": "panduan.md",
        "size_bytes": 1024,
        "status": DocumentStatus.READY,
        "uploaded_at": utc_now(),
        "page_count": 1,
        "chunk_count": 3,
    }
    return Document(**{**defaults, **overrides})  # type: ignore[arg-type]


class TestDocuments:
    def test_tambah_dan_ambil(self, repository: SqliteRepository) -> None:
        document = make_document(id="doc_1")
        repository.add_document(document)
        found = repository.get_document("doc_1")
        assert found is not None
        assert found.filename == "panduan.md"
        assert found.status is DocumentStatus.READY

    def test_ambil_id_tidak_ada_memberi_none(self, repository: SqliteRepository) -> None:
        assert repository.get_document("tidak-ada") is None

    def test_daftar_urutan_terbaru_dulu(self, repository: SqliteRepository) -> None:
        repository.add_document(make_document(id="lama", uploaded_at="2026-01-01T00:00:00+00:00"))
        repository.add_document(make_document(id="baru", uploaded_at="2026-06-01T00:00:00+00:00"))
        assert [item.id for item in repository.list_documents()] == ["baru", "lama"]

    def test_perbarui_status_dan_jumlah_chunk(self, repository: SqliteRepository) -> None:
        repository.add_document(make_document(id="doc_1"))
        repository.update_document("doc_1", status=DocumentStatus.READY, chunk_count=42)
        found = repository.get_document("doc_1")
        assert found is not None
        assert found.chunk_count == 42

    def test_perbarui_field_tidak_dikenal_diabaikan(self, repository: SqliteRepository) -> None:
        repository.add_document(make_document(id="doc_1"))
        # Field di luar daftar putih harus diabaikan, bukan jadi kolom SQL.
        repository.update_document("doc_1", id="direct-injection")
        assert repository.get_document("direct-injection") is None
        assert repository.get_document("doc_1") is not None

    def test_hapus_dokumen_ikut_menghapus_chunk(self, repository: SqliteRepository) -> None:
        from app.models.domain import Chunk  # noqa: PLC0415

        repository.add_document(make_document(id="doc_1"))
        repository.add_chunks(
            [Chunk(id="c1", document_id="doc_1", chunk_index=0, content="isi")], "doc_1"
        )
        repository.delete_document("doc_1")
        assert repository.get_document("doc_1") is None
        _chunks, total = repository.get_chunks("doc_1", 1, 10, None)
        assert total == 0


class TestChunks:
    @pytest.fixture(autouse=True)
    def _seed(self, repository: SqliteRepository) -> None:
        from app.models.domain import Chunk  # noqa: PLC0415

        repository.add_document(make_document(id="doc_1"))
        repository.add_chunks(
            [
                Chunk(
                    id=f"c{index}",
                    document_id="doc_1",
                    chunk_index=index,
                    content=f"Isi chunk nomor {index} dengan teks.",
                    page_number=index + 1,
                )
                for index in range(12)
            ],
            "doc_1",
        )

    def test_pagination_membagi_hasil(self, repository: SqliteRepository) -> None:
        first, total = repository.get_chunks("doc_1", 1, 5, None)
        assert len(first) == 5
        assert total == 12

        third, _ = repository.get_chunks("doc_1", 3, 5, None)
        assert len(third) == 2

    def test_halaman_melebihi_jumlah_tidak_error(self, repository: SqliteRepository) -> None:
        chunks, total = repository.get_chunks("doc_1", 99, 5, None)
        # Melewati halaman terakhir harus mengembalikan daftar kosong, bukan
        # 404 atau error.
        assert chunks == []
        assert total == 12

    def test_urutan_naik_dari_chunk_index(self, repository: SqliteRepository) -> None:
        chunks, _ = repository.get_chunks("doc_1", 1, 5, None)
        assert [chunk.chunk_index for chunk in chunks] == [0, 1, 2, 3, 4]

    def test_pencarian_menyaring_isi(self, repository: SqliteRepository) -> None:
        chunks, total = repository.get_chunks("doc_1", 1, 10, "nomor 7")
        assert total == 1
        assert chunks[0].chunk_index == 7

    def test_total_pencarian_setelah_filter(self, repository: SqliteRepository) -> None:
        # Ini yang dipakai frontend untuk menghitung jumlah halaman, jadi
        # total harus cocok dengan hasil filter, bukan jumlah seluruh dokumen.
        _chunks, total = repository.get_chunks("doc_1", 1, 10, "nomor")
        assert total == 12

    def test_pencarian_tidak_ada_hasil_nol(self, repository: SqliteRepository) -> None:
        chunks, total = repository.get_chunks("doc_1", 1, 10, "katakalamatidakada")
        assert chunks == []
        assert total == 0

    def test_pencarian_kosong_dianggap_tanpa_filter(self, repository: SqliteRepository) -> None:
        _chunks, total = repository.get_chunks("doc_1", 1, 10, "   ")
        assert total == 12

    def test_hapus_chunk(self, repository: SqliteRepository) -> None:
        repository.delete_chunks("doc_1")
        _chunks, total = repository.get_chunks("doc_1", 1, 10, None)
        assert total == 0


class TestSessions:
    def test_tambah_dan_ambil(self, repository: SqliteRepository) -> None:
        repository.upsert_session(
            ChatSession(id="ses_1", title="Percakapan", created_at="2026-01-01T00:00:00+00:00",
                        last_active_at="2026-01-01T00:00:00+00:00", message_count=2)
        )
        found = repository.get_session("ses_1")
        assert found is not None
        assert found.title == "Percakapan"
        assert found.message_count == 2

    def test_daftar_urutan_aktivitas_terakhir(
        self, repository: SqliteRepository
    ) -> None:
        repository.upsert_session(
            ChatSession(id="lama", title="Lama", created_at="2026-01-01T00:00:00+00:00",
                        last_active_at="2026-01-01T00:00:00+00:00")
        )
        repository.upsert_session(
            ChatSession(id="baru", title="Baru", created_at="2026-01-01T00:00:00+00:00",
                        last_active_at="2026-06-01T00:00:00+00:00")
        )
        assert [item.id for item in repository.list_sessions()] == ["baru", "lama"]

    def test_ganti_nama_tidak_mengubah_waktu_aktivitas(
        self, repository: SqliteRepository
    ) -> None:
        repository.upsert_session(
            ChatSession(id="ses_1", title="Awal", created_at="2026-01-01T00:00:00+00:00",
                        last_active_at="2026-03-01T00:00:00+00:00")
        )
        assert repository.rename_session("ses_1", "Nama Baru")

        updated = repository.get_session("ses_1")
        assert updated is not None
        assert updated.title == "Nama Baru"
        # Mengubah nama bukan aktivitas percakapan, jadi waktu aktivitas
        # harus tetap. Kalau berubah, sesi yang cuma dirapikan akan naik ke
        # atas daftar dan urutannya jadi tidak masuk akal.
        assert updated.last_active_at == "2026-03-01T00:00:00+00:00"

    def test_ganti_nama_sesi_tidak_ada_memberi_false(
        self, repository: SqliteRepository
    ) -> None:
        assert repository.rename_session("tidak-ada", "apa saja") is False

    def test_hapus_sesi(self, repository: SqliteRepository) -> None:
        repository.upsert_session(
            ChatSession(id="ses_1", title="X", created_at="2026-01-01T00:00:00+00:00",
                        last_active_at="2026-01-01T00:00:00+00:00")
        )
        assert repository.delete_session("ses_1") is True
        assert repository.get_session("ses_1") is None

    def test_hapus_semua_sesi_mengembalikan_jumlah(
        self, repository: SqliteRepository
    ) -> None:
        for index in range(3):
            repository.upsert_session(
                ChatSession(id=f"ses_{index}", title=f"Sesi {index}",
                            created_at="2026-01-01T00:00:00+00:00",
                            last_active_at="2026-01-01T00:00:00+00:00")
            )
        assert repository.delete_all_sessions() == 3
        assert repository.list_sessions() == []


class TestAllChunks:
    """``all_chunks`` menopang rebuild indeks retrieval saat startup.

    Kalau ini salah, restart kontainer membuat seluruh dokumen lama tidak bisa
    dicari -- dan gejalanya (jawaban "tidak ditemukan") sama sekali tidak
    terlihat sebagai kegagalan.
    """

    def test_kosong_untuk_database_baru(self, repository: SqliteRepository) -> None:
        assert repository.all_chunks() == []

    def test_mengembalikan_chunk_lengkap(
        self, repository: SqliteRepository
    ) -> None:
        from app.models.domain import Document, DocumentStatus

        repository.add_document(
            Document(
                id="doc_a",
                filename="panduan.md",
                size_bytes=100,
                status=DocumentStatus.READY,
                uploaded_at="2026-01-01T00:00:00+00:00",
                page_count=1,
                chunk_count=1,
            )
        )
        repository.add_chunks(
            [
                Chunk(
                    id="doc_a_c1",
                    document_id="doc_a",
                    chunk_index=0,
                    content="isi chunk pertama",
                    page_number=2,
                    token_count=5,
                )
            ],
            "doc_a",
        )

        chunks = repository.all_chunks()
        assert len(chunks) == 1
        chunk = chunks[0]
        assert chunk.id == "doc_a_c1"
        assert chunk.content == "isi chunk pertama"
        # Nama dokumen wajib ikut: sitasi tidak bisa menampilkannya tanpa ini.
        assert chunk.document_name == "panduan.md"
        assert chunk.page_number == 2

    def test_urutan_stabil_antar_dokumen(
        self, repository: SqliteRepository
    ) -> None:
        from app.models.domain import Document, DocumentStatus

        for doc_id in ("doc_a", "doc_b"):
            repository.add_document(
                Document(
                    id=doc_id,
                    filename=f"{doc_id}.md",
                    size_bytes=10,
                    status=DocumentStatus.READY,
                    uploaded_at="2026-01-01T00:00:00+00:00",
                    chunk_count=2,
                )
            )
            for chunk_index in range(2):
                repository.add_chunks(
                    [
                        Chunk(
                            id=f"{doc_id}_c{chunk_index + 1}",
                            document_id=doc_id,
                            chunk_index=chunk_index,
                            content=f"{doc_id} bagian {chunk_index}",
                        )
                    ],
                    doc_id,
                )

        chunks = repository.all_chunks()
        # Urutan harus deterministik, supaya rebuild menghasilkan indeks yang
        # sama setiap kali.
        assert [item.id for item in chunks] == [
            "doc_a_c1",
            "doc_a_c2",
            "doc_b_c1",
            "doc_b_c2",
        ]

    def test_chunk_yah_dokumennya_hilang_tetap_kembali(
        self, repository: SqliteRepository
    ) -> None:
        """Dokumen induk terhapus tapi chunk tersisa tidak boleh menggagalkan rebuild.

        Foreign key di SQLite tidak selalu aktif, jadi kondisi ini bisa terjadi
        setelah penghapusan sebagian. Rebuild yang melempar error akan membuat
        startup gagal total, dan itu lebih buruk daripada nama sumber generik.
        """
        repository.add_chunks(
            [
                Chunk(
                    id="yatim_c1",
                    document_id="dokumen_yang_tidak_ada",
                    chunk_index=0,
                    content="isi tanpa induk",
                )
            ],
            "dokumen_yang_tidak_ada",
        )

        chunks = repository.all_chunks()
        assert len(chunks) == 1
        # Nama cadangan dipakai supaya sitasi tetap punya label.
        assert chunks[0].document_name == "dokumen"

    def test_get_chunks_tidak_bocor_nama_dokumen(
        self, repository: SqliteRepository
    ) -> None:
        """``get_chunks`` tidak melakukan join, jadi kolomnya absen.

        Baris tanpa kolom ``document_name`` harus tetap bisa dibaca, bukan
        melempar KeyError karena akses kolom yang tidak ada.
        """
        from app.models.domain import Document, DocumentStatus

        repository.add_document(
            Document(
                id="doc_a",
                filename="panduan.md",
                size_bytes=100,
                status=DocumentStatus.READY,
                uploaded_at="2026-01-01T00:00:00+00:00",
                chunk_count=1,
            )
        )
        repository.add_chunks(
            [Chunk(id="doc_a_c1", document_id="doc_a", chunk_index=0, content="isi")],
            "doc_a",
        )

        rows, total = repository.get_chunks("doc_a", 1, 10, None)
        assert total == 1
        # Tidak ikut terisi, dan itu tidak boleh menggagalkan apa pun.
        assert rows[0].document_name is None
    def test_default_kalau_belum_diatur(self, repository: SqliteRepository) -> None:
        settings = repository.get_settings()
        # Default harus sesuai rentang yang diizinkan di frontend.
        assert 3 <= settings.top_k <= 10
        assert 0.0 <= settings.similarity_threshold <= 1.0

    def test_perbarui_dan_ambil_kembali(self, repository: SqliteRepository) -> None:
        repository.update_settings({"top_k": 8, "similarity_threshold": 0.6})
        settings = repository.get_settings()
        assert settings.top_k == 8
        assert settings.similarity_threshold == pytest.approx(0.6)

    def test_perbarui_hanya_satu_bagian(self, repository: SqliteRepository) -> None:
        repository.update_settings({"top_k": 7})
        repository.update_settings({"similarity_threshold": 0.4})
        settings = repository.get_settings()
        assert settings.top_k == 7
        assert settings.similarity_threshold == pytest.approx(0.4)

    def test_nilai_none_diabaikan(self, repository: SqliteRepository) -> None:
        repository.update_settings({"top_k": 9})
        repository.update_settings({"top_k": None})
        assert repository.get_settings().top_k == 9


class TestLogs:
    def test_tambah_dan_daftar(self, repository: SqliteRepository) -> None:
        for index in range(5):
            repository.add_log(
                QueryLog(
                    id=f"log_{index}",
                    session_id="ses_1",
                    question=f"Pertanyaan {index}",
                    response_time_ms=1000 + index,
                    sources_count=index,
                    created_at=f"2026-01-0{index + 1}T00:00:00+00:00",
                )
            )
        logs, total = repository.list_logs(1, 3)
        assert total == 5
        assert len(logs) == 3
        # Urutan terbaru lebih dulu.
        assert logs[0].id == "log_4"

    def test_pagination_halaman_kedua(self, repository: SqliteRepository) -> None:
        for index in range(5):
            repository.add_log(
                QueryLog(
                    id=f"log_{index}",
                    session_id=None,
                    question=f"P{index}",
                    response_time_ms=100,
                    sources_count=0,
                    created_at="2026-01-01T00:00:00+00:00",
                )
            )
        logs, total = repository.list_logs(2, 3)
        assert total == 5
        assert len(logs) == 2

    def test_daftar_log_kosong(self, repository: SqliteRepository) -> None:
        logs, total = repository.list_logs(1, 10)
        assert logs == []
        assert total == 0

    def test_latensi_dikelompokkan_per_hari(self, repository: SqliteRepository) -> None:
        repository.add_log(
            QueryLog(id="a", session_id=None, question="x", response_time_ms=1000,
                     sources_count=1, created_at="2026-01-01T10:00:00+00:00")
        )
        repository.add_log(
            QueryLog(id="b", session_id=None, question="y", response_time_ms=2000,
                     sources_count=1, created_at="2026-01-01T11:00:00+00:00")
        )
        repository.add_log(
            QueryLog(id="c", session_id=None, question="z", response_time_ms=4000,
                     sources_count=1, created_at="2026-01-02T10:00:00+00:00")
        )
        points = repository.latency_by_day(14)
        assert len(points) == 2
        assert points[0]["date"] == "2026-01-01"
        assert points[0]["avg_ms"] == 1500
        assert points[1]["date"] == "2026-01-02"

    def test_p95_terukti_dari_durasi_asli(self, repository: SqliteRepository) -> None:
        for index in range(20):
            repository.add_log(
                QueryLog(
                    id=f"log_{index}",
                    session_id=None,
                    question="x",
                    response_time_ms=(index + 1) * 100,
                    sources_count=1,
                    created_at="2026-01-01T00:00:00+00:00",
                )
            )
        point = repository.latency_by_day(14)[0]
        # p95 harus salah satu durasi yang benar-benar tercatat, bukan
        # hasil interpolasi yang tidak pernah terjadi.
        assert point["p95_ms"] in {value * 100 for value in range(1, 21)}

    def test_token_per_hari(self, repository: SqliteRepository) -> None:
        repository.add_log(
            QueryLog(id="a", session_id=None, question="pertanyaan panjang sekali",
                     response_time_ms=100, sources_count=2, created_at="2026-01-01T00:00:00+00:00")
        )
        points = repository.tokens_by_day(14)
        assert points
        assert points[0]["input_tokens"] > 0
        assert points[0]["output_tokens"] > 0

    def test_token_tanpa_log_kosong(self, repository: SqliteRepository) -> None:
        assert repository.tokens_by_day(14) == []


class TestEval:
    def test_tidak_ada_eval_memberi_none(self, repository: SqliteRepository) -> None:
        assert repository.latest_eval() is None

    def test_simpan_dan_ambil_yang_terbaru(self, repository: SqliteRepository) -> None:
        repository.add_eval_run(
            {"id": "eval_1", "precision": 0.8, "faithfulness": 0.9,
             "answer_relevance": 0.7, "run_at": "2026-01-01T00:00:00+00:00"}
        )
        repository.add_eval_run(
            {"id": "eval_2", "precision": 0.85, "faithfulness": 0.92,
             "answer_relevance": 0.8, "run_at": "2026-06-01T00:00:00+00:00"}
        )
        latest = repository.latest_eval()
        assert latest is not None
        assert latest["id"] == "eval_2"
        assert latest["precision"] == pytest.approx(0.85)

    def test_nilai_kosong_disimpan_sebagai_null(self, repository: SqliteRepository) -> None:
        repository.add_eval_run({"id": "eval_1", "run_at": "2026-01-01T00:00:00+00:00"})
        latest = repository.latest_eval()
        assert latest is not None
        # Skor yang belum dihitung harus None, bukan 0. Angka nol berarti
        # "skornya nol", yang berbeda dari "belum ada skor".
        assert latest["precision"] is None


class TestHealth:
    def test_ping_berhasil(self, repository: SqliteRepository) -> None:
        assert repository.ping() is True


class TestIdGenerator:
    def test_id_unik(self) -> None:
        ids = {new_id("doc") for _ in range(100)}
        assert len(ids) == 100

    def test_id_memakai_prefix(self) -> None:
        assert new_id("ses").startswith("ses_")
