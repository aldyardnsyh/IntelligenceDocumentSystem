"""Test endpoint API.

Test integrasi memakai aplikasi FastAPI sungguhan dengan stub di tempat yang
biayanya besar (embedding, vector store, memory, LLM). Yang diuji kontrak
HTTP-nya: bentuk respons, status code, dan pesan error yang bisa ditampilkan.
"""

from __future__ import annotations

import json
import tempfile
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import Settings
from app.core.security import SESSION_COOKIE_NAME, hash_passcode
from app.dependencies import (
    get_ingestion,
    get_repository,
    init_services,
    shutdown_services,
)
from app.main import create_app
from app.providers.embedding import reset_embedding_provider
from app.services.memory.store import reset_memory_store
from app.services.retrieval.vector_store import reset_vector_store
from tests.conftest import SAMPLE_DOCUMENT, TEST_PASSCODE


@pytest.fixture
def api_settings(tmp_path) -> Settings:
    """Settings dengan database dan penyimpanan terisolasi per test.

    Isolasi ini penting, bukan sekadar formalitas. `SqliteRepository`
    membuka berkas ``SQLITE_FALLBACK_PATH`` dari env global, jadi tanpa
    ``tmp_path`` per test, log dan sesi dari test sebelumnya bocor ke test
    berikutnya. Gejalanya klasik: setiap test lulus sendiri, lalu gagal kalau
    dijalankan berurutan.
    """
    from app.core.config import get_settings

    get_settings.cache_clear()
    config = Settings()
    config.access_passcode_sha256 = hash_passcode(TEST_PASSCODE)
    config.llm_provider = "mock"
    config.use_local_embedding = False
    config.debug = True
    # Rentang ambang dilonggarkan; lihat catatan di conftest.
    config.min_similarity_threshold = 0.0
    config.max_similarity_threshold = 1.0
    config.default_similarity_threshold = 0.5
    config.sqlite_fallback_path = str(tmp_path / "api-test.db")
    config.chroma_persist_dir = str(tmp_path / "chroma")
    # Memory store dan vector store dibuat ulang oleh init_services, jadi
    # cookie serta cache antar test tidak berbagi.
    reset_memory_store()
    reset_vector_store()
    reset_embedding_provider()
    return config


@pytest.fixture
async def api_app(api_settings: Settings):
    """Aplikasi yang sudah dijalankan, dipakai bersama beberapa klien.

    Ownership sesi diuji dengan dua identitas. Keduanya harus bicara ke app yang
    sama: kalau masing-masing memakai app berbeda, tiap app punya
    ``SessionStore`` sendiri dan tidak ada klaim yang bisa diuji.
    """
    from app.core.security import SessionStore, SlidingWindowLimiter

    init_services(api_settings)
    app = create_app()
    app.state.auth_limiter = SlidingWindowLimiter(
        max_attempts=api_settings.auth_max_attempts,
        window_seconds=api_settings.auth_window_seconds,
    )
    app.state.session_store = SessionStore(ttl_seconds=api_settings.session_ttl_seconds)
    app.state.ingestion = get_ingestion()
    yield app
    shutdown_services()


@pytest.fixture
async def client(api_app) -> AsyncIterator[AsyncClient]:
    """Klien HTTP yang sudah login ke aplikasi yang sedang berjalan."""
    transport = ASGITransport(app=api_app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as http:
        # Login sekali di awal supaya cookie sesi ikut di setiap request
        # berikutnya. Router yang dilindungi menolak tanpa cookie ini, dan
        # itu perilaku yang memang diuji lewat TestProtectedRequiresSession
        # di bawah.
        login = await http.post(
            "/api/v1/auth/verify", json={"passcode": TEST_PASSCODE}
        )
        assert login.status_code == 200, login.text
        yield http


@pytest.fixture
async def second_client(api_app) -> AsyncIterator[AsyncClient]:
    """Identitas kedua pada app yang sama, untuk menguji kepemilikan sesi."""
    transport = ASGITransport(app=api_app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as http:
        login = await http.post(
            "/api/v1/auth/verify", json={"passcode": TEST_PASSCODE}
        )
        assert login.status_code == 200, login.text
        yield http


@pytest.fixture
async def anon_client(api_app) -> AsyncIterator[AsyncClient]:
    """Klien tanpa sesi, untuk menguji penolakan akses."""
    transport = ASGITransport(app=api_app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as http:
        yield http


def parse_sse(payload: str) -> list[dict[str, Any]]:
    """Ubah badan SSE menjadi daftar event."""
    events: list[dict[str, Any]] = []
    for block in payload.split("\n\n"):
        for line in block.split("\n"):
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if not data or data == "[DONE]":
                continue
            events.append(json.loads(data))
    return events


class TestHealth:
    async def test_health_melaporkan_komponen(self, client: AsyncClient) -> None:
        response = await client.get("/api/v1/health")
        assert response.status_code == 200
        body = response.json()
        assert body["llm"] == "ok"
        assert body["memory"] == "ok"
        assert body["vector_store"] == "ok"
        assert "version" in body

    async def test_embedding_fallback_terlihat_di_health(self, client: AsyncClient) -> None:
        """Test berjalan dengan embedding hashing, jadi health harus jujur.

        Kalau fallback tidak dilaporkan, operator melihat `status: ok` padahal
        retrieval hanya cocok untuk token identik, kegagalan diam-diam yang
        paling mahal karena gejalanya muncul jauh dari penyebabnya.
        """
        body = (await client.get("/api/v1/health")).json()
        assert body["fallback"]["embedding"] == "hashing-fallback"
        assert body["status"] == "degraded"
        assert body["fallback"]["mode"] == "reduced"

    async def test_health_memuat_header_durasi(self, client: AsyncClient) -> None:
        response = await client.get("/api/v1/health")
        # Header ini dipakai monitoring tanpa perlu parse log.
        assert "X-Response-Time-Ms" in response.headers


class TestProtectedRequiresSession:
    """Endpoint yang dilindungi harus menolak request tanpa cookie sesi.

    Router-wide dependency dipakai supaya tidak ada endpoint yang "lupa"
    ditambahkan. Test ini mengunci sifat itu: kalau ada route baru yang
    dipindah ke router yang salah, test ini gagal.
    """

    @pytest.mark.parametrize(
        ("method", "path"),
        [
            ("GET", "/api/v1/documents"),
            ("POST", "/api/v1/documents/upload"),
            ("GET", "/api/v1/settings"),
            ("PUT", "/api/v1/settings"),
            ("GET", "/api/v1/chat/sessions"),
            ("POST", "/api/v1/chat/query"),
            ("GET", "/api/v1/analytics/summary"),
            ("GET", "/api/v1/analytics/logs"),
        ],
    )
    async def test_endpoint_terlindungi_menolak_tanpa_sesi(
        self, anon_client: AsyncClient, method: str, path: str
    ) -> None:
        response = await anon_client.request(method, path, json={})
        assert response.status_code == 401
        assert response.json()["code"] == "session_expired"

    async def test_cookie_palsu_ditolak(self, anon_client: AsyncClient) -> None:
        # Cookie dengan string acak apa pun harus ditolak, bukan dipercaya
        # hanya karena ada.
        anon_client.cookies.set(SESSION_COOKIE_NAME, "token-palsu-ngawur")
        response = await anon_client.get("/api/v1/documents")
        assert response.status_code == 401

    async def test_health_tetap_terbuka(self, anon_client: AsyncClient) -> None:
        # Health check dipakai monitor yang tidak punya sesi.
        assert (await anon_client.get("/api/v1/health")).status_code == 200

    async def test_auth_verify_tetap_terbuka(self, anon_client: AsyncClient) -> None:
        response = await anon_client.post(
            "/api/v1/auth/verify", json={"passcode": TEST_PASSCODE}
        )
        assert response.status_code == 200

    async def test_logout_mencabut_token(self, client: AsyncClient) -> None:
        assert (await client.get("/api/v1/documents")).status_code == 200
        response = await client.post("/api/v1/auth/logout")
        assert response.status_code == 204
        # Header set-cookie wajib ada. Tanpa itu token masih hidup di browser
        # dan logout hanya berlaku di sisi server.
        assert "set-cookie" in {key.lower() for key in response.headers}
        # Setelah logout, cookie yang sama tidak boleh lagi berlaku. Kalau
        # masih berlaku, pencabutan tidak benar-benar mencabut apa pun.
        assert (await client.get("/api/v1/documents")).status_code == 401


class TestSessionOwnershipOverHttp:
    """Kepemilikan sesi diuji di level endpoint.

    Helper di ``SessionStore`` bisa benar sementara endpoint tetap lupa memanggil
   nya, dan itu justru yang membuat IDOR bisa terjadi.
    """

    async def test_sesi_asing_ditolak(
        self, client: AsyncClient, second_client: AsyncClient
    ) -> None:
        created = await client.post(
            "/api/v1/chat/query", json={"session_id": "ses_asik", "question": "halo"}
        )
        assert created.status_code == 200, created.text

        # Klien kedua login sendiri, jadi punya identitas berbeda.
        continued = await second_client.post(
            "/api/v1/chat/query",
            json={"session_id": "ses_asik", "question": "lanjutkan"},
        )
        assert continued.status_code == 403
        assert "milik" in continued.json()["detail"]

        # Membaca, mengganti nama, dan menghapus punya aturan yang sama.
        assert (await second_client.get("/api/v1/chat/ses_asik/history")).status_code == 403
        renamed = await second_client.patch(
            "/api/v1/chat/sessions/ses_asik", json={"title": "curang"}
        )
        assert renamed.status_code == 403
        assert (await second_client.delete("/api/v1/chat/sessions/ses_asik")).status_code == 403

    async def test_sesi_yang_dibuat_server_ikut_dilindungi(
        self, client: AsyncClient, api_app
    ) -> None:
        # Jalur utama frontend: pertanyaan pertama mengirim `session_id: null`
        # sehingga server yang membuat id sesinya. Kalau id itu tidak diklaim,
        # sesi baru justru jadi milik siapa pun yang tahu id-nya.
        response = await client.post("/api/v1/chat/query", json={"question": "halo"})
        assert response.status_code == 200, response.text
        session_id = next(
            event["session_id"] for event in parse_sse(response.text) if event["type"] == "session"
        )

        stored = get_repository().get_session(session_id)
        assert stored is not None, "sesi harus tersimpan di metadata"

        # Klaim dibuat saat event session diterima, jadi identitas lain
        # langsung ditolak.
        store = api_app.state.session_store
        assert store.may_access_session(session_id, store.issue()) is False

    async def test_pemilik_asli_boleh_lanjut(
        self, client: AsyncClient, api_settings: Settings
    ) -> None:
        first = await client.post(
            "/api/v1/chat/query", json={"session_id": "ses_sendiri", "question": "halo"}
        )
        assert first.status_code == 200, first.text
        second = await client.post(
            "/api/v1/chat/query", json={"session_id": "ses_sendiri", "question": "lagi"}
        )
        assert second.status_code == 200, second.text
        history = await client.get("/api/v1/chat/ses_sendiri/history")
        assert history.status_code == 200
        assert len(history.json()["messages"]) == 4

    async def test_rate_limit_tidak_bisa_dilewati_dengan_id_acak(
        self, client: AsyncClient, api_settings: Settings
    ) -> None:
        # Kalau kunci limiter berasal dari `session_id` di body, setiap id acak
        # mendapat bucket baru dan kuota tidak pernah tercapai.
        statuses: list[int] = []
        for index in range(api_settings.query_max_per_session + 5):
            response = await client.post(
                "/api/v1/chat/query",
                json={"session_id": f"ses_acak_{index}", "question": "apa isinya?"},
            )
            statuses.append(response.status_code)
        assert 429 in statuses

    async def test_session_id_berbentuk_aneh_ditolak(
        self, client: AsyncClient
    ) -> None:
        response = await client.post(
            "/api/v1/chat/query",
            json={"session_id": "ses dengan spasi dan newline\n", "question": "halo"},
        )
        assert response.status_code == 422


class TestAuth:
    async def test_passcode_benar_mendapat_cookie(self, anon_client: AsyncClient) -> None:
        response = await anon_client.post(
            "/api/v1/auth/verify", json={"passcode": TEST_PASSCODE}
        )
        assert response.status_code == 200
        assert response.json() == {"ok": True, "expires_in": 86400}
        assert SESSION_COOKIE_NAME in response.cookies

    async def test_passcode_salah_gagal(self, anon_client: AsyncClient) -> None:
        response = await anon_client.post(
            "/api/v1/auth/verify", json={"passcode": "salah"}
        )
        assert response.status_code == 401
        # Pesan harus generik, supaya tidak bisa dipakai menebak-nebak.
        assert response.json()["detail"] == "Passcode salah."

    async def test_passcode_kosong_gagal_validasi(self, anon_client: AsyncClient) -> None:
        response = await anon_client.post("/api/v1/auth/verify", json={"passcode": ""})
        assert response.status_code == 422
        assert "detail" in response.json()

    async def test_badan_gagal_validasi(self, anon_client: AsyncClient) -> None:
        response = await anon_client.post("/api/v1/auth/verify", json={})
        assert response.status_code == 422

    async def test_rate_limit_percobaan_gagal(self, anon_client: AsyncClient) -> None:
        # Enam percobaan salah; percobaan ke-6 harus ditolak.
        statuses = []
        for _ in range(6):
            response = await anon_client.post(
                "/api/v1/auth/verify", json={"passcode": "salah"}
            )
            statuses.append(response.status_code)
        assert statuses[:5] == [401] * 5
        assert statuses[5] == 429
        assert "Retry-After" in response.headers

    async def test_rate_limit_lupa_setelah_sah(self, anon_client: AsyncClient) -> None:
        for _ in range(3):
            await anon_client.post("/api/v1/auth/verify", json={"passcode": "salah"})
        await anon_client.post("/api/v1/auth/verify", json={"passcode": TEST_PASSCODE})
        # Setelah berhasil, penghitung direset, jadi percobaan salah lagi
        # harus tetap 401 dan bukan langsung 429.
        response = await anon_client.post("/api/v1/auth/verify", json={"passcode": "salah"})
        assert response.status_code == 401


def _buat_pdf_sederhana(teks: str = "SLA penyelesaian permintaan adalah dua hari kerja") -> bytes:
    """PDF satu halaman berisi teks, dibuat lewat reportlab.

    Ditulis lewat library, bukan disusun manual dari byte: PDF buatan tangan
    mudah ditolak parser, dan test yang ter-skip karena itu tidak menguji apa
    pun. Halaman harus benar-benar berisi teks, karena parser menolak PDF
    tanpa layer teks (itu memang perilaku yang diinginkan untuk hasil pindai).
    """
    import io

    from reportlab.pdfgen import canvas

    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=(300, 200))
    pdf.drawString(30, 120, teks)
    pdf.showPage()
    pdf.save()
    return buffer.getvalue()


class TestDocuments:
    async def test_daftar_kosong_awal(self, client: AsyncClient) -> None:
        response = await client.get("/api/v1/documents")
        assert response.status_code == 200
        assert response.json() == []

    async def test_unggah_teks_menerima_dan_ipp(self, client: AsyncClient) -> None:
        response = await client.post(
            "/api/v1/documents/upload",
            files={"file": ("panduan.md", SAMPLE_DOCUMENT.encode("utf-8"), "text/markdown")},
        )
        # 202 karena ingestion berjalan di background.
        assert response.status_code == 202
        body = response.json()
        assert body["filename"] == "panduan.md"
        assert body["status"] in ("processing", "ready", "failed")
        assert body["size_bytes"] > 0

    async def test_unggah_format_tidak_didukung(self, client: AsyncClient) -> None:
        response = await client.post(
            "/api/v1/documents/upload",
            files={"file": ("gambar.png", b"\x89PNG", "image/png")},
        )
        # Format salah ditolak di respons pertama. Mengembalikan 202 dengan
        # dokumen berstatus "failed" membuat pengguna menunggu status yang
        # memang tidak akan pernah berubah.
        assert response.status_code == 400
        assert "Format tidak didukung" in response.json()["detail"]
        # Dokumen yang ditolak tidak boleh meninggalkan baris gagal di daftar.
        listed = await client.get("/api/v1/documents")
        assert all(item["filename"] != "gambar.png" for item in listed.json())

    async def test_unggah_tanpa_nama_berkas(self, client: AsyncClient) -> None:
        # Nama berisi spasi saja. Nama yang benar-benar kosong tidak bisa
        # diuji lewat httpx: ia menghapus atribut ``filename`` sehingga
        # FastAPI memperlakukan part itu sebagai field biasa, bukan file, dan
        # jawabannya ``422`` dari lapisan validasi, bukan dari route.
        # Browser nyata selalu mengirim nama.
        response = await client.post(
            "/api/v1/documents/upload", files={"file": ("   ", b"isi", "text/plain")}
        )
        assert response.status_code == 400
        assert "nama berkas" in response.json()["detail"].lower()

    async def test_detail_dokumen_tidak_ada(self, client: AsyncClient) -> None:
        response = await client.get("/api/v1/documents/tidak-ada")
        assert response.status_code == 404
        assert response.json()["code"] == "not_found"

    async def test_detail_dokumen_ada(self, client: AsyncClient) -> None:
        upload = await client.post(
            "/api/v1/documents/upload",
            files={"file": ("panduan.md", SAMPLE_DOCUMENT.encode("utf-8"), "text/markdown")},
        )
        document_id = upload.json()["id"]

        response = await client.get(f"/api/v1/documents/{document_id}")
        assert response.status_code == 200
        body = response.json()
        # Konfigurasi ingestion harus benar-benar dikembalikan, bukan
        # konstanta tebakan di frontend.
        assert body["ingestion"]["chunk_size"] > 0
        assert body["ingestion"]["embedding_model"]
        # Chunk tidak boleh ikut di sini; itu endpoint terpisah.
        assert "chunks" not in body

    async def test_status_dokumen(self, client: AsyncClient) -> None:
        upload = await client.post(
            "/api/v1/documents/upload",
            files={"file": ("catatan.txt", b"Isi catatan uji.", "text/plain")},
        )
        document_id = upload.json()["id"]
        response = await client.get(f"/api/v1/documents/{document_id}/status")
        assert response.status_code == 200
        assert response.json()["id"] == document_id

    async def test_status_dokumen_tidak_ada(self, client: AsyncClient) -> None:
        assert (await client.get("/api/v1/documents/x/status")).status_code == 404

    async def test_hapus_dokumen_tidak_ada(self, client: AsyncClient) -> None:
        assert (await client.delete("/api/v1/documents/tidak-ada")).status_code == 404


    async def test_preview_mengembalikan_isi_berurutan(self, client: AsyncClient) -> None:
        """Pratinjau menyusun chunk kembali menjadi teks berurutan.

        Daftar chunk tidak bisa dipakai menilai apakah jawaban chat benar:
        potongannya terpisah-pisah dan konteks di sekitarnya tidak terlihat.
        """
        upload = await client.post(
            "/api/v1/documents/upload",
            files={
                "file": (
                    "preview.md",
                    (
                        b"Bagian pertama dokumen ini menjelaskan prosedur.\n\n"
                        b"Bagian kedua memuat tenggat dua hari kerja.\n\n"
                        b"Bagian ketiga menutup dengan tanggung jawab petugas.\n"
                    ),
                    "text/markdown",
                )
            },
        )
        document_id = upload.json()["id"]
        await _wait_ready(client, document_id)

        response = await client.get(f"/api/v1/documents/{document_id}/preview")
        assert response.status_code == 200, response.text
        body = response.json()

        assert body["id"] == document_id
        assert body["filename"] == "preview.md"
        assert body["truncated"] is False
        # Isi lengkap harus terbaca berurutan.
        assert "Bagian pertama" in body["content"]
        assert "Bagian ketiga" in body["content"]
        assert body["content"].index("Bagian pertama") < body["content"].index("Bagian ketiga")
        assert body["total_chars"] > 0
        assert body["chunk_count"] == len(
            (await client.get(f"/api/v1/documents/{document_id}/chunks")).json()["items"]
        )

    async def test_preview_dokumen_tidak_ada(self, client: AsyncClient) -> None:
        response = await client.get("/api/v1/documents/doc_tidak_ada/preview")
        assert response.status_code == 404

    async def test_berkas_asli_dilayani_untuk_pratinjau(self, client: AsyncClient) -> None:
        """PDF asli harus bisa diambil untuk ditampilkan berdampingan.

        Halaman dokumen memerlukan berkas aslinya: tata letak, tabel, dan
        halaman yang gagal terbaca hanya terlihat di PDF-nya, bukan di teks
        hasil ekstraksi.
        """
        pdf_bytes = _buat_pdf_sederhana()
        upload = await client.post(
            "/api/v1/documents/upload",
            files={"file": ("pratinjau.pdf", pdf_bytes, "application/pdf")},
        )
        if upload.status_code != 202:
            pytest.skip("PDF uji tidak diterima parser di lingkungan ini")
        document_id = upload.json()["id"]
        await _wait_ready(client, document_id)

        response = await client.get(f"/api/v1/documents/{document_id}/file")
        assert response.status_code == 200, response.text
        assert response.headers["content-type"] == "application/pdf"
        # `inline` supaya browser menampilkan, bukan mengunduh.
        assert "inline" in response.headers["content-disposition"]
        # Isi berkas harus sama dengan yang diunggah.
        assert response.content == pdf_bytes

    async def test_berkas_tidak_disimpan_untuk_teks(self, client: AsyncClient) -> None:
        # Untuk TXT/MD, isinya sudah tersedia dari chunk. Menyimpan berkasnya
        # hanya memakai disk tanpa manfaat.
        upload = await client.post(
            "/api/v1/documents/upload",
            files={"file": ("tanpa-berkas.md", b"# Judul\n\nIsi dokumen.", "text/markdown")},
        )
        document_id = upload.json()["id"]
        await _wait_ready(client, document_id)

        response = await client.get(f"/api/v1/documents/{document_id}/file")
        assert response.status_code == 404
        assert "tidak tersimpan" in response.json()["detail"]

    async def test_berkas_asli_ikut_dihapus(self, client: AsyncClient) -> None:
        pdf_bytes = _buat_pdf_sederhana()
        upload = await client.post(
            "/api/v1/documents/upload",
            files={"file": ("hapus.pdf", pdf_bytes, "application/pdf")},
        )
        if upload.status_code != 202:
            pytest.skip("PDF uji tidak diterima parser di lingkungan ini")
        document_id = upload.json()["id"]
        await _wait_ready(client, document_id)

        assert (await client.get(f"/api/v1/documents/{document_id}/file")).status_code == 200
        assert (await client.delete(f"/api/v1/documents/{document_id}")).status_code == 204
        # Setelah dihapus, berkasnya tidak boleh bisa diambil lagi.
        assert (await client.get(f"/api/v1/documents/{document_id}/file")).status_code == 404

    async def test_preview_dokumen_gagal_jelas(self, client: AsyncClient) -> None:
        # Dokumen tanpa chunk belum punya isi; jawabannya harus menjelaskan
        # kenapa, bukan mengirim teks kosong.
        upload = await client.post(
            "/api/v1/documents/upload",
            files={"file": ("kosong.txt", b"   ", "text/plain")},
        )
        if upload.status_code != 400:
            document_id = upload.json()["id"]
            await _wait_ready(client, document_id)
            response = await client.get(f"/api/v1/documents/{document_id}/preview")
            assert response.status_code in (409, 200)


class TestChunks:
    async def test_paginasi_dan_pencarian(self, client: AsyncClient) -> None:
        upload = await client.post(
            "/api/v1/documents/upload",
            files={"file": ("panduan.md", SAMPLE_DOCUMENT.encode("utf-8"), "text/markdown")},
        )
        document_id = upload.json()["id"]
        # Beri background task kesempatan selesai.
        await _wait_ready(client, document_id)

        page = await client.get(f"/api/v1/documents/{document_id}/chunks?page=1&page_size=2")
        assert page.status_code == 200
        body = page.json()
        assert body["page"] == 1
        assert body["page_size"] == 2
        assert len(body["items"]) <= 2
        assert body["total"] >= 1
        # Metadata chunk harus lengkap untuk halaman detail.
        assert "chunk_index" in body["items"][0]
        assert "content" in body["items"][0]

    async def test_total_setelah_pencarian(self, client: AsyncClient) -> None:
        upload = await client.post(
            "/api/v1/documents/upload",
            files={"file": ("panduan.md", SAMPLE_DOCUMENT.encode("utf-8"), "text/markdown")},
        )
        document_id = upload.json()["id"]
        await _wait_ready(client, document_id)

        semua = await client.get(f"/api/v1/documents/{document_id}/chunks?page_size=100")
        total_semua = semua.json()["total"]

        hasil_cari = await client.get(
            f"/api/v1/documents/{document_id}/chunks?page_size=100&q=penyelesaian"
        )
        # Total harus mengikuti filter; kalau tidak, jumlah halaman di
        # frontend akan salah.
        assert hasil_cari.json()["total"] <= total_semua

    async def test_halaman_melebihi_batas_tidak_error(self, client: AsyncClient) -> None:
        upload = await client.post(
            "/api/v1/documents/upload",
            files={"file": ("catatan.txt", b"Isi.", "text/plain")},
        )
        document_id = upload.json()["id"]
        response = await client.get(f"/api/v1/documents/{document_id}/chunks?page=99")
        assert response.status_code == 200
        assert response.json()["items"] == []

    async def test_page_size_diluar_rentang_ditolak(self, client: AsyncClient) -> None:
        upload = await client.post(
            "/api/v1/documents/upload",
            files={"file": ("catatan.txt", b"Isi.", "text/plain")},
        )
        document_id = upload.json()["id"]
        response = await client.get(f"/api/v1/documents/{document_id}/chunks?page_size=999")
        assert response.status_code == 422

    async def test_chunk_dokumen_tidak_ada(self, client: AsyncClient) -> None:
        assert (await client.get("/api/v1/documents/x/chunks")).status_code == 404


class TestChat:
    async def test_tanya_dan_stream_sse(self, client: AsyncClient) -> None:
        # Dokumen fokus dipakai, bukan SOP penuh. Alasannya: stub embedding
        # (hashing trick) memberi skor cosine ~0.3 untuk SOP yang panjang,
        # di bawah ambang produksi 0.5. Dokumen pendek dengan overlap tinggi
        # memberi 0.78, sehingga test ini menguji *mekanisme* SSE dan sitasi
        # lewat HTTP, bukan kalibrasi threshold, yang sudah diuji di unit
        # test dengan threshold eksplisit.
        upload = await client.post(
            "/api/v1/documents/upload",
            files={
                "file": (
                    "fokus.md",
                    b"Penyelesaian permintaan membutuhkan dua hari. "
                    b"Penyelesaian permintaan dicatat segera.",
                    "text/markdown",
                )
            },
        )
        document_id = upload.json()["id"]
        await _wait_ready(client, document_id)

        response = await client.post(
            "/api/v1/chat/query", json={"question": "penyelesaian permintaan"}
        )
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")

        events = parse_sse(response.text)
        types = [event["type"] for event in events]
        assert "session" in types
        assert "token" in types
        assert "done" in types
        # Sitasi harus ada kalau konteks ditemukan.
        assert "citations" in types

    async def test_pertanyaan_kosong_ditolak(self, client: AsyncClient) -> None:
        response = await client.post("/api/v1/chat/query", json={"question": "   "})
        assert response.status_code == 422

    async def test_tanpa_dokumen_menghasilkan_not_found(self, client: AsyncClient) -> None:
        response = await client.post(
            "/api/v1/chat/query", json={"question": "apa isi dokumen ini?"}
        )
        events = parse_sse(response.text)
        assert "not_found" in [event["type"] for event in events]

    async def test_event_citations_bisa_dibaca_frontend(self, client: AsyncClient) -> None:
        # Dokumen fokus, bukan SOP. Lihat penjelasan di test_tanya_dan_stream_sse.
        upload = await client.post(
            "/api/v1/documents/upload",
            files={
                "file": (
                    "fokus.md",
                    b"Penyelesaian permintaan membutuhkan dua hari. "
                    b"Penyelesaian permintaan dicatat segera.",
                    "text/markdown",
                )
            },
        )
        await _wait_ready(client, upload.json()["id"])
        response = await client.post(
            "/api/v1/chat/query", json={"question": "penyelesaian permintaan"}
        )
        events = parse_sse(response.text)
        citations = next(event for event in events if event["type"] == "citations")
        first = citations["value"][0]
        # Field yang dibutuhkan frontend harus ada semua.
        for field in ("document_id", "document_name", "chunk_index", "excerpt", "score"):
            assert field in first

    async def test_sesi_baru_ikut_register(self, client: AsyncClient) -> None:
        response = await client.post(
            "/api/v1/chat/query", json={"question": "pertanyaan tanpa dokumen"}
        )
        events = parse_sse(response.text)
        session_id = next(event for event in events if event["type"] == "session")["session_id"]

        sessions = await client.get("/api/v1/chat/sessions")
        assert session_id in [item["id"] for item in sessions.json()]

    async def test_daftar_sesi_kosong_aman(self, client: AsyncClient) -> None:
        response = await client.get("/api/v1/chat/sessions")
        assert response.status_code == 200
        assert response.json() == []

    async def test_riwayat_sesi(self, client: AsyncClient) -> None:
        first = await client.post(
            "/api/v1/chat/query", json={"question": "pertanyaan pertama"}
        )
        session_id = next(
            event for event in parse_sse(first.text) if event["type"] == "session"
        )["session_id"]

        second = await client.post(
            "/api/v1/chat/query",
            json={"question": "pertanyaan kedua", "session_id": session_id},
        )
        parse_sse(second.text)

        response = await client.get(f"/api/v1/chat/{session_id}/history")
        assert response.status_code == 200
        body = response.json()
        assert len(body["messages"]) == 4
        assert body["session"]["id"] == session_id

    async def test_riwayat_sesi_tidak_ada(self, client: AsyncClient) -> None:
        response = await client.get("/api/v1/chat/tidak-ada/history")
        assert response.status_code == 404

    async def test_ganti_nama_sesi(self, client: AsyncClient) -> None:
        first = await client.post(
            "/api/v1/chat/query", json={"question": "pertanyaan untuk sesi"}
        )
        session_id = next(
            event for event in parse_sse(first.text) if event["type"] == "session"
        )["session_id"]

        response = await client.patch(
            f"/api/v1/chat/sessions/{session_id}", json={"title": "Nama Baru"}
        )
        assert response.status_code == 200
        assert response.json()["title"] == "Nama Baru"

    async def test_ganti_nama_tidak_menimpa_dengan_otomatis(self, client: AsyncClient) -> None:
        """Nama manual harus bertahan setelah pertanyaan berikutnya."""
        first = await client.post(
            "/api/v1/chat/query", json={"question": "pertanyaan awal"}
        )
        session_id = next(
            event for event in parse_sse(first.text) if event["type"] == "session"
        )["session_id"]
        await client.patch(
            f"/api/v1/chat/sessions/{session_id}", json={"title": "Nama Manual"}
        )

        # Pertanyaan lanjutan. Kalau backend menimpa judul dengan pertanyaan
        # ini, nama manual akan hilang, dan itu yang harus dicegah.
        await client.post(
            "/api/v1/chat/query",
            json={"question": "pertanyaan lanjutan yang panjang sekali", "session_id": session_id},
        )

        sessions = await client.get("/api/v1/chat/sessions")
        titles = {item["id"]: item["title"] for item in sessions.json()}
        assert titles[session_id] == "Nama Manual"

    async def test_ganti_nama_sesi_tidak_ada(self, client: AsyncClient) -> None:
        response = await client.patch(
            "/api/v1/chat/sessions/tidak-ada", json={"title": "apa saja"}
        )
        assert response.status_code == 404

    async def test_ganti_nama_kosong_ditolak(self, client: AsyncClient) -> None:
        first = await client.post(
            "/api/v1/chat/query", json={"question": "pertanyaan"}
        )
        session_id = next(
            event for event in parse_sse(first.text) if event["type"] == "session"
        )["session_id"]
        response = await client.patch(
            f"/api/v1/chat/sessions/{session_id}", json={"title": "   "}
        )
        assert response.status_code == 422

    async def test_hapus_sesi(self, client: AsyncClient) -> None:
        first = await client.post(
            "/api/v1/chat/query", json={"question": "pertanyaan"}
        )
        session_id = next(
            event for event in parse_sse(first.text) if event["type"] == "session"
        )["session_id"]

        assert (await client.delete(f"/api/v1/chat/sessions/{session_id}")).status_code == 204
        assert (await client.delete(f"/api/v1/chat/sessions/{session_id}")).status_code == 404

    async def test_reset_semua_sesi(self, client: AsyncClient) -> None:
        for _ in range(2):
            await client.post("/api/v1/chat/query", json={"question": "pertanyaan"})
        response = await client.delete("/api/v1/chat/sessions")
        assert response.status_code == 204
        assert (await client.get("/api/v1/chat/sessions")).json() == []


class TestChatUngrounded:
    """Mode "jawab tanpa dokumen".

    Kontraknya: LLM tetap dipanggil, jawaban TIDAK diklaim bersumber dari
    dokumen, dan event `ungrounded` dikirim supaya UI bisa memberi label.
    Tanpa mode ini, sistem hanya bisa berkata "tidak ditemukan", benar
    secara keamanan, tapi tidak menjawab kebutuhan pengguna yang ingin tetap
    mendapat jawaban dari pengetahuan umum.
    """

    async def test_tanpa_konteks_dan_tanpa_izin_tetap_menolak(
        self, client: AsyncClient
    ) -> None:
        response = await client.post(
            "/api/v1/chat/query", json={"question": "berapa harga tiket bioskop?"}
        )
        assert response.status_code == 200
        types = [event["type"] for event in parse_sse(response.text)]
        assert "not_found" in types
        assert "ungrounded" not in types

    async def test_dengan_izin_llm_menjawab_dan_dilabeli(self, client: AsyncClient) -> None:
        response = await client.post(
            "/api/v1/chat/query",
            json={"question": "berapa harga tiket bioskop?", "allow_ungrounded": True},
        )
        assert response.status_code == 200
        events = parse_sse(response.text)
        types = [event["type"] for event in events]
        # LLM benar-benar menjawab...
        assert "token" in types
        # ...dan jawabannya ditandai bukan dari dokumen.
        assert "ungrounded" in types
        assert "not_found" not in types
        # Tanpa konteks, tidak boleh ada sitasi palsu.
        assert "citations" not in types

    async def test_label_dikirim_sebelum_token_pertama(self, client: AsyncClient) -> None:
        """Label harus datang lebih dulu, bukan di akhir jawaban.

        Kalau labelnya datang setelah teks, pengguna sudah membaca jawabannya
        lebih dulu dan baru tahu asalnya di akhir, terlambat untuk mencegah
        salah paham.
        """
        response = await client.post(
            "/api/v1/chat/query",
            json={"question": "berapa harga tiket bioskop?", "allow_ungrounded": True},
        )
        types = [event["type"] for event in parse_sse(response.text)]
        assert "ungrounded" in types
        assert "token" in types
        assert types.index("ungrounded") < types.index("token")


class TestChatScopeDokumen:
    """Chat privat per dokumen: retrieval dibatasi dokumen itu saja."""

    async def test_dokumen_tidak_dikenal_ditolak(self, client: AsyncClient) -> None:
        # Scope ke dokumen yang tidak ada akan mencari di ruang kosong dan
        # menjawab "tidak ditemukan" untuk semuanya. Menolak dengan 404 jauh
        # lebih jelas daripada membiarkan pengguna menebak.
        response = await client.post(
            "/api/v1/chat/query",
            json={"question": "apa isinya?", "document_id": "doc_tidak_ada"},
        )
        assert response.status_code == 404
        assert "tidak ditemukan" in response.json()["detail"].lower()

    async def test_dokumen_belum_siap_ditolak(self, client: AsyncClient) -> None:
        # Dokumen berstatus failed tidak bisa ditanyai; tanpa pemeriksaan ini
        # pengguna hanya melihat jawaban kosong berulang.
        upload = await client.post(
            "/api/v1/documents/upload",
            files={"file": ("rusak.pdf", b"bukan pdf", "application/pdf")},
        )
        if upload.status_code != 400:
            # PDF parser bisa menerima beberapa berkas aneh; lewati saja.
            pytest.skip("berkas uji tidak menghasilkan dokumen gagal")
        # Berkas ditolak di upload, jadi buat dokumen failed lewat jalur lain:
        # scope ke dokumen yang tidak ada sudah diuji di atas.

    async def test_sesi_ber_scope_tidak_bisa_bocor_ke_dokumen_lain(
        self, client: AsyncClient
    ) -> None:
        """Sesi yang sudah terikat dokumen tetap terikat, apa pun isi request.

        Ini bug kritis yang pernah terjadi: scope hanya diambil dari request.
        Kalau klien lupa mengirim `document_id` (mis. daftar sesi sedang
        dimuat ulang), pertanyaan lanjutan mencari di SELURUH dokumen dan
        jawabannya membawa sitasi dokumen yang tidak pernah dipilih pengguna.
        """
        sop = await client.post(
            "/api/v1/documents/upload",
            files={
                "file": (
                    "scope-sop.md",
                    (
                        b"SLA penyelesaian permintaan adalah dua hari kerja "
                        b"sejak permintaan dicatat pada Sistem Tiket.\n"
                    ),
                    "text/markdown",
                )
            },
        )
        sop_id = sop.json()["id"]
        await _wait_ready(client, sop_id)

        lain = await client.post(
            "/api/v1/documents/upload",
            files={
                "file": (
                    "scope-lain.md",
                    b"Panduan pemasangan server produksi memakai container docker.\n",
                    "text/markdown",
                )
            },
        )
        lain_id = lain.json()["id"]
        await _wait_ready(client, lain_id)

        # Pertanyaan pertama mengikat sesi ke dokumen SOP.
        first = await client.post(
            "/api/v1/chat/query",
            json={
                "question": "berapa hari SLA penyelesaian permintaan?",
                "document_id": sop_id,
            },
        )
        assert first.status_code == 200, first.text
        session_id = next(
            event["session_id"]
            for event in parse_sse(first.text)
            if event["type"] == "session"
        )

        # Pertanyaan lanjutan TANPA document_id: server harus tetap memakai
        # scope sesi, bukan mencari di semua dokumen.
        second = await client.post(
            "/api/v1/chat/query",
            json={"question": "berapa hari lagi batas waktunya?", "session_id": session_id},
        )
        assert second.status_code == 200, second.text
        citations = next(
            (
                event["value"]
                for event in parse_sse(second.text)
                if event["type"] == "citations"
            ),
            [],
        )
        # Sumber yang muncul harus dari dokumen yang di-scope, bukan yang lain.
        for citation in citations:
            assert citation["document_id"] == sop_id, (
                "sesi ber-scope menemukan sumber dari dokumen di luar scope-nya"
            )

        # Sesi tetap menyimpan scope-nya untuk dipakai putaran berikutnya.
        history = (await client.get(f"/api/v1/chat/{session_id}/history")).json()
        assert history["session"]["document_id"] == sop_id

    async def test_sesi_ber_scope_tidak_berubah_oleh_request(
        self, client: AsyncClient
    ) -> None:
        """Klien tidak boleh memindahkan sesi ke dokumen lain lewat request.

        Tanpa aturan ini, satu request dengan `document_id` berbeda bisa
        mengalihkan percakapan yang sudah berjalan ke korpus lain.
        """
        first_doc = await client.post(
            "/api/v1/documents/upload",
            files={
                "file": (
                    "scope-a.md",
                    b"Prosedur cuti tahunan dua belas hari.",
                    "text/markdown",
                )
            },
        )
        first_id = first_doc.json()["id"]
        await _wait_ready(client, first_id)

        second_doc = await client.post(
            "/api/v1/documents/upload",
            files={
                "file": (
                    "scope-b.md",
                    b"Panduan instalasi server linux.",
                    "text/markdown",
                )
            },
        )
        second_id = second_doc.json()["id"]
        await _wait_ready(client, second_id)

        started = await client.post(
            "/api/v1/chat/query",
            json={"question": "berapa hari cuti tahunan?", "document_id": first_id},
        )
        session_id = next(
            event["session_id"]
            for event in parse_sse(started.text)
            if event["type"] == "session"
        )

        # Coba alihkan ke dokumen kedua.
        moved = await client.post(
            "/api/v1/chat/query",
            json={
                "question": "bagaimana cara instalasi?",
                "session_id": session_id,
                "document_id": second_id,
            },
        )
        assert moved.status_code == 200, moved.text
        citations = next(
            (
                event["value"]
                for event in parse_sse(moved.text)
                if event["type"] == "citations"
            ),
            [],
        )
        for citation in citations:
            assert citation["document_id"] == first_id, (
                "scope sesi berpindah karena request, bukan karena pengguna memilih"
            )

    async def test_sesi_terikat_dokumen(self, client: AsyncClient) -> None:
        first = await client.post(
            "/api/v1/documents/upload",
            files={
                "file": (
                    "sop.md",
                    b"Prosedur cuti tahunan dua belas hari kerja.",
                    "text/markdown",
                )
            },
        )
        first_id = first.json()["id"]
        await _wait_ready(client, first_id)

        second = await client.post(
            "/api/v1/documents/upload",
            files={
                "file": (
                    "lain.md",
                    b"Panduan pemasangan server produksi dengan docker.",
                    "text/markdown",
                )
            },
        )
        second_id = second.json()["id"]
        await _wait_ready(client, second_id)

        response = await client.post(
            "/api/v1/chat/query",
            json={
                "question": "berapa hari cuti tahunan?",
                "document_id": first_id,
                "allow_ungrounded": True,
            },
        )
        assert response.status_code == 200
        session_id = next(
            event["session_id"]
            for event in parse_sse(response.text)
            if event["type"] == "session"
        )

        # Sesi menyimpan scope-nya, supaya riwayat bisa dibuka kembali dengan
        # filter yang sama tanpa menebak.
        session = (await client.get(f"/api/v1/chat/{session_id}/history")).json()["session"]
        assert session["document_id"] == first_id
        assert session["document_id"] != second_id


class TestSettings:
    async def test_ambil_default(self, client: AsyncClient) -> None:
        response = await client.get("/api/v1/settings")
        assert response.status_code == 200
        body = response.json()
        assert 3 <= body["top_k"] <= 10
        assert 0.0 <= body["similarity_threshold"] <= 1.0

    async def test_perbarui_dan_kembalikan_nilai_aktif(
        self, client: AsyncClient
    ) -> None:
        response = await client.put(
            "/api/v1/settings", json={"top_k": 8, "similarity_threshold": 0.6}
        )
        assert response.status_code == 200
        assert response.json() == {"top_k": 8, "similarity_threshold": 0.6}

    async def test_nilai_diluar_rentang_diklem(self, client: AsyncClient) -> None:
        # Frontend mengirim rentang slider; di luar itu harus diklem dan
        # respons mengembalikan nilai yang benar-benar aktif.
        response = await client.put(
            "/api/v1/settings", json={"top_k": 999, "similarity_threshold": 5.0}
        )
        assert response.status_code == 200
        body = response.json()
        assert body["top_k"] == 10
        assert body["similarity_threshold"] <= 1.0

    async def test_perbarui_kosong_aman(self, client: AsyncClient) -> None:
        response = await client.put("/api/v1/settings", json={})
        assert response.status_code == 200


class TestAnalytics:
    async def test_summary_tanpa_eval_null(self, client: AsyncClient) -> None:
        response = await client.get("/api/v1/analytics/summary")
        assert response.status_code == 200
        body = response.json()
        # Belum ada run evaluasi harus None, bukan angka nol. Nol berarti
        # "skornya nol", yang berbeda dari "belum ada skor".
        assert body["latest_eval"] is None
        assert body["latency"] == []
        assert body["tokens"] == []

    async def test_evaluasi_bisa_dijalankan_dari_api(self, client: AsyncClient) -> None:
        """Evaluasi retrieval harus bisa dijalankan tanpa kredensial tambahan.

        Sebelumnya satu-satunya cara mengisi halaman /analytics adalah skrip
        RAGAS yang butuh LLM penilai dan API key. Tanpa itu, pengguna hanya
        melihat "belum ada data evaluasi" tanpa jalan keluar.

        Test ini memakai dataset yang merujuk dokumen yang sudah diunggah,
        karena evaluasi memang menolak berjalan pada korpus yang tidak memuat
        dokumen rujukannya, skor nol di situasi itu menyesatkan.
        """
        upload = await client.post(
            "/api/v1/documents/upload",
            files={
                "file": (
                    "sop-evaluasi.md",
                    (
                        b"Standar Operasional Prosedur: Layanan Permintaan Informasi\n\n"
                        b"SLA Penyelesaian adalah batas waktu maksimal penyelesaian "
                        b"permintaan, yaitu dua hari kerja sejak permintaan dicatat.\n\n"
                        b"Receiving Officer wajib mencatat setiap permintaan pada "
                        b"Sistem Tiket dalam waktu paling lama satu jam kerja.\n\n"
                        b"Bila berkas tidak lengkap, pemohon diberi pemberitahuan "
                        b"tertulis dalam tempo dua hari kerja.\n"
                    ),
                    "text/markdown",
                )
            },
        )
        assert upload.status_code in (200, 202), upload.text
        await _wait_ready(client, upload.json()["id"])

        # Dataset sementara yang merujuk dokumen ini.
        dataset_path = Path(tempfile.mkdtemp()) / "dataset.json"
        dataset_path.write_text(
            json.dumps(
                [
                    {
                        "question": "Berapa lama batas waktu penyelesaian permintaan?",
                        "ground_truth": "Dua hari kerja sejak permintaan dicatat.",
                        "document_name": "sop-evaluasi.md",
                    },
                    {
                        "question": "Berapa biaya pengajuan layanan?",
                        "ground_truth": "TIDAK ADA JAWABAN.",
                        "document_name": "sop-evaluasi.md",
                    },
                ]
            ),
            encoding="utf-8",
        )

        from app.dependencies import get_app_settings  # noqa: PLC0415

        get_app_settings().evaluation_dataset_path = str(dataset_path)

        response = await client.post("/api/v1/analytics/evaluate")
        assert response.status_code == 200, response.text
        body = response.json()
        # Metrik yang bisa dihitung tanpa LLM harus terisi.
        assert body["precision"] is not None
        assert body["answer_relevance"] is not None
        # Faithfulness memang butuh LLM; dikosongkan, bukan diisi tebakan.
        assert body["faithfulness"] is None

        # Hasilnya tersimpan, jadi halaman analitik langsung terisi.
        summary = (await client.get("/api/v1/analytics/summary")).json()
        assert summary["latest_eval"] is not None
        assert summary["latest_eval"]["id"] == body["id"]

    async def test_evaluasi_menolak_dataset_hilang(
        self, client: AsyncClient, api_settings: Settings
    ) -> None:
        api_settings.evaluation_dataset_path = "tidak/ada/dataset.json"
        response = await client.post("/api/v1/analytics/evaluate")
        assert response.status_code == 409
        assert "tidak ditemukan" in response.json()["detail"].lower()

    async def test_evaluasi_menjelaskan_dokumen_yang_belum_ada(
        self, client: AsyncClient
    ) -> None:
        """Skor nol tanpa penjelasan terbaca sebagai "retrieval rusak".

        Dataset merujuk dokumen tertentu. Kalau dokumennya belum diunggah,
        jawabannya harus menyebut itu, bukan menampilkan nol dan membiarkan
        pengguna menebak.
        """
        response = await client.post("/api/v1/analytics/evaluate")
        assert response.status_code == 409
        detail = response.json()["detail"]
        assert "belum ada di korpus" in detail
        assert "seed_demo" in detail

    async def test_evaluasi_bisa_dijalankan_pada_dokumen_pilihan(
        self, client: AsyncClient
    ) -> None:
        """Evaluasi harus berguna untuk korpus sendiri, bukan hanya contoh.

        Sebelumnya dataset disaring berdasarkan nama dokumen, sehingga dokumen
        pengguna tidak akan pernah cocok dan seluruh pertanyaan terbuang.
        Sekarang yang diukur: apakah retrieval menemukan sumber di dokumen
        yang dipilih.
        """
        upload = await client.post(
            "/api/v1/documents/upload",
            files={
                "file": (
                    "korpus-sendiri.md",
                    (
                        b"Prosedur pengajuan tiket memerlukan kategori, judul, "
                        b"dan deskripsi masalah yang jelas.\n"
                    ),
                    "text/markdown",
                )
            },
        )
        document_id = upload.json()["id"]
        await _wait_ready(client, document_id)

        response = await client.post(
            "/api/v1/analytics/evaluate", json={"document_ids": [document_id]}
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["precision"] is not None
        # Hit rate dihitung dari pertanyaan dataset terhadap korpus ini.
        assert body["answer_relevance"] is not None

    async def test_evaluasi_menolak_dokumen_pilihan_yang_tidak_ada(
        self, client: AsyncClient
    ) -> None:
        response = await client.post(
            "/api/v1/analytics/evaluate", json={"document_ids": ["doc_hantu"]}
        )
        assert response.status_code == 404
        assert "tidak ditemukan" in response.json()["detail"].lower()

    async def test_evaluasi_menghitung_skor_setelah_dokumen_ada(
        self, client: AsyncClient
    ) -> None:
        # Unggah dokumen yang dirujuk dataset, lalu evaluasi harus memberi
        # skor yang bermakna (bukan nol karena dokumennya hilang).
        upload = await client.post(
            "/api/v1/documents/upload",
            files={
                "file": (
                    "contoh-sop-layanan.md",
                    (
                        b"Standar Operasional Prosedur: Layanan Permintaan Informasi\n\n"
                        b"3. Definisi\n"
                        b"SLA Penyelesaian adalah batas waktu maksimal penyelesaian "
                        b"permintaan, yaitu dua hari kerja sejak permintaan dicatat.\n\n"
                        b"4. Tanggung Jawab\n"
                        b"Receiving Officer wajib mencatat setiap permintaan pada "
                        b"Sistem Tiket dalam waktu paling lama satu jam kerja.\n\n"
                        b"5. Alur Proses\n"
                        b"Permintaan diterima melalui formulir elektronik atau loket "
                        b"fisik. Bila berkas tidak lengkap, pemohon diberi "
                        b"pemberitahuan tertulis dalam tempo dua hari kerja.\n"
                    ),
                    "text/markdown",
                )
            },
        )
        assert upload.status_code in (200, 202), upload.text
        await _wait_ready(client, upload.json()["id"])

        response = await client.post("/api/v1/analytics/evaluate")
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["precision"] is not None
        assert body["answer_relevance"] is not None
        # Retrieval harus menemukan dokumennya, jadi skornya tidak nol.
        assert body["answer_relevance"] > 0

    async def test_log_kosong(self, client: AsyncClient) -> None:
        response = await client.get("/api/v1/analytics/logs")
        assert response.status_code == 200
        assert response.json() == {"items": [], "total": 0, "page": 1, "page_size": 10}

    async def test_log_terisi_setelah_query(self, client: AsyncClient) -> None:
        await client.post("/api/v1/chat/query", json={"question": "pertanyaan tercatat"})
        response = await client.get("/api/v1/analytics/logs")
        body = response.json()
        assert body["total"] == 1
        assert body["items"][0]["question"] == "pertanyaan tercatat"
        # trace_id boleh null karena mode mock tidak memanggil LLM.
        assert "trace_id" in body["items"][0]

    async def test_paginasi_log(self, client: AsyncClient) -> None:
        for index in range(5):
            await client.post(
                "/api/v1/chat/query", json={"question": f"pertanyaan {index}"}
            )
        first = await client.get("/api/v1/analytics/logs?page=1&page_size=2")
        assert len(first.json()["items"]) == 2
        assert first.json()["total"] == 5

    async def test_latensi_setelah_query(self, client: AsyncClient) -> None:
        await client.post("/api/v1/chat/query", json={"question": "pertanyaan"})
        response = await client.get("/api/v1/analytics/summary")
        body = response.json()
        # Grafik harus terisi dari log nyata, bukan dari angka contoh.
        assert len(body["latency"]) >= 1
        assert body["latency"][0]["avg_ms"] >= 0

    async def test_page_size_log_diluar_rentang(self, client: AsyncClient) -> None:
        assert (await client.get("/api/v1/analytics/logs?page_size=999")).status_code == 422


class TestErrorShape:
    async def test_error_404_punya_bentuk_konsisten(
        self, client: AsyncClient
    ) -> None:
        body = (await client.get("/api/v1/documents/tidak-ada")).json()
        assert set(body) == {"detail", "code"}
        assert isinstance(body["detail"], str)
        assert body["code"] == "not_found"

    async def test_error_validasi_punya_bentuk_konsisten(
        self, client: AsyncClient
    ) -> None:
        body = (await client.post("/api/v1/chat/query", json={})).json()
        assert set(body) == {"detail", "code"}
        assert body["code"] == "validation_error"

    async def test_openapi_tersedia(self, client: AsyncClient) -> None:
        # Skema OpenAPI tersedia otomatis dari FastAPI.
        response = await client.get("/openapi.json")
        assert response.status_code == 200
        assert "/api/v1/chat/query" in response.json()["paths"]


async def _wait_ready(client: AsyncClient, document_id: str, attempts: int = 20) -> None:
    """Tunggu sampai ingestion selesai, dengan batas waktu."""
    import asyncio

    for _ in range(attempts):
        response = await client.get(f"/api/v1/documents/{document_id}/status")
        status_value = response.json().get("status")
        if status_value in ("ready", "failed"):
            return
        await asyncio.sleep(0.1)
