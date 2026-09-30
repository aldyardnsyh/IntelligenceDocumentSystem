"""Test endpoint API.

Test integrasi memakai aplikasi FastAPI sungguhan dengan stub di tempat yang
biayanya besar (embedding, vector store, memory, LLM). Yang diuji kontrak
HTTP-nya: bentuk respons, status code, dan pesan error yang bisa ditampilkan.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import Settings
from app.core.security import SESSION_COOKIE_NAME, hash_passcode
from app.dependencies import get_ingestion, init_services, shutdown_services
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
    config.sqlite_fallback_path = str(tmp_path / "api-test.db")
    config.chroma_persist_dir = str(tmp_path / "chroma")
    # Memory store dan vector store dibuat ulang oleh init_services, jadi
    # cookie serta cache antar test tidak berbagi.
    reset_memory_store()
    reset_vector_store()
    reset_embedding_provider()
    return config


@pytest.fixture
async def client(api_settings: Settings) -> AsyncIterator[AsyncClient]:
    """Klien HTTP yang sudah login ke aplikasi yang sedang berjalan."""
    from app.core.security import SessionStore, SlidingWindowLimiter

    init_services(api_settings)
    app = create_app()

    # Lifespan tidak dijalankan otomatis oleh ASGITransport, jadi state yang
    # biasanya diisi di lifespan di sini diisi manual. Menjalankan lifespan
    # sungguhan lewat TestClient akan menutup service global dan membuat test
    # saling memengaruhi.
    app.state.auth_limiter = SlidingWindowLimiter(
        max_attempts=api_settings.auth_max_attempts,
        window_seconds=api_settings.auth_window_seconds,
    )
    app.state.session_store = SessionStore(
        ttl_seconds=api_settings.session_ttl_seconds
    )
    app.state.ingestion = get_ingestion()

    transport = ASGITransport(app=app)
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
    shutdown_services()


@pytest.fixture
async def anon_client(api_settings: Settings) -> AsyncIterator[AsyncClient]:
    """Klien tanpa sesi, untuk menguji penolakan akses."""
    from app.core.security import SessionStore, SlidingWindowLimiter

    init_services(api_settings)
    app = create_app()
    app.state.auth_limiter = SlidingWindowLimiter(
        max_attempts=api_settings.auth_max_attempts,
        window_seconds=api_settings.auth_window_seconds,
    )
    app.state.session_store = SessionStore(
        ttl_seconds=api_settings.session_ttl_seconds
    )
    app.state.ingestion = get_ingestion()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as http:
        yield http
    shutdown_services()


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
    async def test_health_ok(self, client: AsyncClient) -> None:
        response = await client.get("/api/v1/health")
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ok"
        assert body["llm"] == "ok"
        assert "version" in body

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
        # Enam percobaan salah; percobaan ke-6 harus ditolak (TC-09).
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
        # 202 karena ingestion berjalan di background (FR-1.1).
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
        assert response.status_code == 202
        # Format salah tidak melempar error, tapi dokumen dicatat sebagai gagal
        # dengan pesan yang bisa ditampilkan.
        body = response.json()
        assert body["status"] == "failed"
        assert "Format tidak didukung" in body["error_message"]

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
        upload = await client.post(
            "/api/v1/documents/upload",
            files={"file": ("panduan.md", SAMPLE_DOCUMENT.encode("utf-8"), "text/markdown")},
        )
        document_id = upload.json()["id"]
        await _wait_ready(client, document_id)

        response = await client.post(
            "/api/v1/chat/query", json={"question": "berapa hari untuk penyelesaian"}
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
        upload = await client.post(
            "/api/v1/documents/upload",
            files={"file": ("panduan.md", SAMPLE_DOCUMENT.encode("utf-8"), "text/markdown")},
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
        # PRD 5.3 menyebut auto-dokumentasi; itu gratis dari FastAPI.
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
