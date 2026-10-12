"""Aplikasi FastAPI.

Titik masuk backend. Yang penting di sini:

- **Error handler seragam.** Semua kegagalan dikembalikan dengan bentuk
  ``{"detail": ..., "code": ...}`` yang sudah dikonsumsi frontend, jadi
  halaman selalu punya pesan yang bisa ditampilkan, bukan traceback.
- **CORS terbatas.** Hanya origin yang terdaftar, bukan ``*``, karena API ini
  memegang dokumen pengguna.
- **Swagger otomatis.** Skema OpenAPI dan halaman ``/docs`` didapat gratis dari
  FastAPI, jadi kontrak API selalu ikut versi kode.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.v1.routes import public_router
from app.api.v1.routes import router as v1_router
from app.core.config import get_settings
from app.core.security import SessionStore, SlidingWindowLimiter
from app.dependencies import (
    get_ingestion,
    get_repository,
    init_services,
    shutdown_services,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Bangun service saat start, lepaskan saat berhenti.

    Embedding model dimuat di sini, bukan per request. Memuatnya per request
    akan menambah beberapa detik ke setiap panggilan.
    """
    settings = get_settings()
    init_services(settings)

    # Konfigurasi yang berbahaya di produksi diperiksa saat start, bukan
    # dibiarkan lewat tanpa jejak. Semuanya ditulis sebagai peringatan keras,
    # bukan crash: aplikasi yang jalan dengan satu setelan salah masih lebih
    # berguna daripada yang tidak bisa start sama sekali, dan log yang jelas
    # membuat penyebabnya bisa ditemukan.
    _warn_unsafe_production_settings(settings)

    app.state.auth_limiter = SlidingWindowLimiter(
        max_attempts=settings.auth_max_attempts,
        window_seconds=settings.auth_window_seconds,
    )
    app.state.session_store = SessionStore(ttl_seconds=settings.session_ttl_seconds)
    # Penanda proses ini, dibaca frontend lewat health. Nilainya berubah tiap
    # start, dan itu yang dipakai untuk tahu bahwa state browser yang tersisa
    # berasal dari proses yang sudah mati.
    app.state.boot_id = uuid.uuid4().hex[:12]

    # Sesi akses dan riwayat percakapan hidup di memori proses. Setelah
    # restart keduanya kosong, jadi data lama di SQLite hanya akan menjadi
    # riwayat yatim: sesi yang muncul di sidebar tapi isinya tidak bisa
    # dibuka, dan pertanyaan lanjutan yang kehilangan konteksnya.
    #
    # Karena itu riwayat dibersihkan saat start, dan cookie sesi lama di
    # browser sengaja tidak berlaku lagi, pengguna diminta masuk ulang.
    # Ini juga yang membuat "build ulang" berarti build ulang: tidak ada
    # state lama yang diam-diam ikut terbawa.
    purged = await asyncio.to_thread(get_repository().delete_all_sessions)
    if purged:
        logger.info(
            "Riwayat sesi lama dibersihkan saat start: %d sesi. "
            "Sesi memori tidak bertahan melewati restart, jadi menyisakannya "
            "hanya menghasilkan riwayat yang tidak bisa dibuka.",
            purged,
        )

    # Disimpan di state supaya shutdown bisa menunggu ingestion yang sedang
    # berjalan, bukan hanya service-nya yang dilepas.
    app.state.ingestion = get_ingestion()
    logger.info("%s v%s siap", settings.app_name, settings.version)
    try:
        yield
    finally:
        # Tunggu ingestion yang masih jalan supaya dokumen tidak tertinggal
        # di status ``processing`` kalau proses dimatikan saat startup.
        ingestion = getattr(app.state, "ingestion", None)
        if ingestion is not None:
            await ingestion.wait_pending()
        shutdown_services()
        logger.info("Layanan dilepas.")


def create_app() -> FastAPI:
    """Bangun aplikasi. Dipisah supaya test bisa membuat instance sendiri."""
    settings = get_settings()

    app = FastAPI(
        title=settings.app_name,
        version=settings.version,
        description=(
            "Backend RAG: ingestion dokumen, retrieval hybrid, generasi jawaban "
            "berantai fallback provider, memori sesi, dan analitik evaluasi."
        ),
        lifespan=lifespan,
        # Dokumentasi interaktif dimatikan secara default. Skema OpenAPI
        # memuat seluruh bentuk request dan response termasuk nama field
        # internal, dan /docs membiarkan siapa pun mencoba endpoint tanpa
        # menulis kode. Untuk aplikasi yang menampilkan dokumen pribadi, itu
        # permukaan yang tidak perlu terbuka. Nyalakan dengan API_DOCS_ENABLED=1
        # kalau memang dipakai sebagai demo portofolio.
        docs_url="/docs" if settings.api_docs_enabled else None,
        redoc_url="/redoc" if settings.api_docs_enabled else None,
        openapi_url="/openapi.json" if settings.api_docs_enabled else None,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def add_timing_header(request: Request, call_next):  # noqa: ANN001, ANN202
        """Tambahkan header durasi, supaya latency bisa dipantau tanpa log."""
        started = time.perf_counter()
        response = await call_next(request)
        elapsed_ms = (time.perf_counter() - started) * 1000
        response.headers["X-Response-Time-Ms"] = f"{elapsed_ms:.1f}"
        return response

    # ------------------------------------------------------ error handlers
    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(
        request: Request, exc: StarletteHTTPException
    ) -> JSONResponse:
        """Bentuk error seragam.

        ``detail`` dari HTTPException sudah ditulis untuk dibaca orang.
        Exception lain disembunyikan dari pesan supaya detail internal tidak
        bocor ke klien, tapi tetap dicatat di log server.
        """
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": str(exc.detail), "code": _code_for(exc.status_code)},
            headers=getattr(exc, "headers", None),
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        """Ubah pesan validasi Pydantic jadi kalimat yang bisa dibaca."""
        problems = exc.errors()
        if problems:
            first = problems[0]
            location = ".".join(str(item) for item in first.get("loc", ()) if item != "body")
            field = location or "input"
            message = first.get("msg", "nilai tidak valid")
            detail = f"Field '{field}': {message}"
        else:
            detail = "Data yang dikirim tidak valid."
        return JSONResponse(
            status_code=422,
            content={"detail": detail, "code": "validation_error"},
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        """Tangkap error tak terduga.

        Pesannya sengaja generik. Detail aslinya ada di log server, karena
        membocorkan traceback ke klien bisa membocorkan struktur internal
        dan path berkas.
        """
        logger.exception("Error tak tertangani di %s %s", request.method, request.url.path)
        return JSONResponse(
            status_code=500,
            content={
                "detail": "Layanan mengalami gangguan. Coba lagi sebentar lagi.",
                "code": "internal_error",
            },
        )

    app.include_router(public_router)
    app.include_router(v1_router)
    return app


def _warn_unsafe_production_settings(settings: object) -> None:
    """Catat konfigurasi yang berbahaya kalau aplikasi ini di-host.

    Semua ini adalah setelan yang "supaya cepat jalan" di mesin sendiri, tapi
    berbahaya begitu ada di internet. Tidak ada yang mematikan aplikasi:
    yang gagal start tidak akan dibaca lognya oleh siapa pun, dan operator
    lebih baik melihat layanan jalan dengan pesan jelas di log daripada
    container yang crash-loop tanpa penjelasan.
    """
    from app.core.config import Settings  # noqa: PLC0415

    assert isinstance(settings, Settings)

    if settings.debug:
        logger.warning(
            "DEBUG=true aktif. Jangan pakai ini di server yang bisa diakses "
            "publik: pesan error internal ikut terkirim ke klien."
        )

    if settings.llm_provider == "mock":
        logger.warning(
            "LLM_PROVIDER=mock: jawaban yang muncul adalah cuplikan dokumen, "
            "bukan sintesis LLM. Set LLM_PROVIDER=groq atau ollama untuk "
            "penggunaan nyata."
        )

    if not settings.access_passcode_sha256:
        logger.error(
            "ACCESS_PASSCODE_SHA256 belum diisi. SEMUA percobaan login akan "
            "ditolak sampai nilainya diisi. Buat dengan: "
            "python -m scripts.make_passcode"
        )

    if settings.api_docs_enabled:
        logger.warning(
            "API_DOCS_ENABLED aktif: /docs, /redoc, dan /openapi.json terbuka "
            "tanpa autentikasi. Matikan kecuali aplikasi ini memang demo publik."
        )

    insecure_origins = [
        origin for origin in settings.cors_origins if origin.startswith("http://")
    ]
    if insecure_origins:
        # `http://localhost` wajar saat pengembangan; yang berbahaya adalah
        # origin http:// untuk domain sungguhan.
        non_local = [o for o in insecure_origins if "localhost" not in o and "127.0.0.1" not in o]
        if non_local:
            logger.warning(
                "CORS_ORIGINS memuat origin http:// untuk host non-lokal: %s. "
                "Cookie sesi sebaiknya hanya dikirim lewat HTTPS.",
                ", ".join(non_local),
            )


def _code_for(status_code: int) -> str:
    return {
        400: "invalid_request",
        401: "session_expired",
        404: "not_found",
        409: "conflict",
        413: "file_too_large",
        422: "validation_error",
        429: "rate_limited",
        503: "unavailable",
    }.get(status_code, "internal_error" if status_code >= 500 else "error")


app = create_app()
