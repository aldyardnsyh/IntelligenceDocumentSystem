"""Aplikasi FastAPI.

Titik masuk backend. Yang penting di sini:

- **Error handler seragam.** Semua kegagalan dikembalikan dengan bentuk
  ``{"detail": ..., "code": ...}`` yang sudah dikonsumsi frontend, jadi
  halaman selalu punya pesan yang bisa ditampilkan, bukan traceback.
- **CORS terbatas.** Hanya origin yang terdaftar, bukan ``*``, karena API ini
  memegang dokumen pengguna.
- **Swagger otomatis.** PRD 5.3 menyebut auto-dokumentasi; itu gratis dari
  FastAPI.
"""

from __future__ import annotations

import logging
import time
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
from app.dependencies import get_ingestion, init_services, shutdown_services

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
    app.state.auth_limiter = SlidingWindowLimiter(
        max_attempts=settings.auth_max_attempts,
        window_seconds=settings.auth_window_seconds,
    )
    app.state.session_store = SessionStore(ttl_seconds=settings.session_ttl_seconds)
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
