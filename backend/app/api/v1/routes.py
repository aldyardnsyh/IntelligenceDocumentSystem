"""Route API v1.

Semua handler mengikuti aturan yang sama: kalau ada yang gagal, pesan error
ditulis untuk dibaca orang, bukan exception mentah. Bentuk error seragam ada
di ``app.main`` lewat exception handler.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from typing import Annotated, Literal

from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
    status,
)
from fastapi.responses import StreamingResponse

from app.core.config import Settings
from app.core.security import SESSION_COOKIE_NAME, SlidingWindowLimiter, verify_passcode
from app.dependencies import (
    get_app_settings,
    get_ingestion,
    get_rag,
    get_rate_limiter,
    get_repository,
)
from app.models.schemas import (
    AnalyticsLogsResponse,
    AnalyticsSummaryResponse,
    ChatHistoryResponse,
    ChatQueryRequest,
    ChunkPage,
    DocumentDetail,
    DocumentStatusResponse,
    DocumentSummary,
    EvalRunResponse,
    HealthResponse,
    IngestionInfo,
    LatencyPoint,
    PasscodeRequest,
    PasscodeResponse,
    SessionRenameRequest,
    SettingsResponse,
    SettingsUpdate,
    TokenPoint,
    chunk_to_response,
    document_to_detail,
    document_to_summary,
    log_to_response,
    message_to_response,
    session_to_response,
)
from app.repositories.sqlite_repo import MetadataRepository
from app.services.ingestion.service import IngestionService
from app.services.memory.rate_limit import RateLimiter
from app.services.rag_service import RagService

logger = logging.getLogger(__name__)

#: Alias dependency. Dipakai sebagai ``Annotated[..., Depends(...)]`` supaya
#: signature handler tetap satu baris.
SettingsDep = Annotated[Settings, Depends(get_app_settings)]
RepositoryDep = Annotated[MetadataRepository, Depends(get_repository)]
RagDep = Annotated[RagService, Depends(get_rag)]
IngestionDep = Annotated[IngestionService, Depends(get_ingestion)]
LimiterDep = Annotated[RateLimiter, Depends(get_rate_limiter)]


# ------------------------------------------------------------------- auth


async def require_session(request: Request, config: SettingsDep) -> None:
    """Pastikan request bawa cookie sesi yang sah (FR-0.2).

    Diberikan sebagai dependency router-wide, bukan ditulis ulang di setiap
    handler. Menulisnya manual di setiap endpoint berarti ada satu endpoint yang
    akan lupa, dan endpoint yang lupa itu adalah yang bocor.

    Cookie dibuat ``httponly`` saat diterbitkan, jadi tidak bisa dibaca
    JavaScript. Frontend juga menyimpan gate-nya sendiri; cookie ini adalah
    lapisan kedua di sisi API.
    """
    del config  # Dependency hanya untuk memicu inisialisasi service.
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if not token or not request.app.state.session_store.is_valid(token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Sesi berakhir. Masuk kembali dengan passcode.",
        )


#: Router publik. Hanya endpoint yang harus bisa dipanggil tanpa sesi:
#: verifikasi passcode, pencabutan sesi, dan health check untuk monitoring.
public_router = APIRouter(prefix="/api/v1")

#: Router yang dilindungi. ``dependencies`` di level router memastikan setiap
#: endpoint yang ditambahkan di sini otomatis ikut terlindungi, tanpa perlu
#: mengingat menambahkannya per-handler.
router = APIRouter(
    prefix="/api/v1",
    dependencies=[Depends(require_session)],
)


@public_router.post("/auth/verify", response_model=PasscodeResponse)
async def verify_passcode_endpoint(
    request: Request,
    response: Response,
    payload: PasscodeRequest,
    config: SettingsDep,
) -> PasscodeResponse:
    """Verifikasi passcode lalu set cookie sesi (FR-0.1, FR-0.2).

    Pesan kegagalan sengaja tidak membedakan "passcode salah" dari
    "passcode tidak terdaftar", supaya tidak ada yang bisa menebak.
    """
    client_ip = request.client.host if request.client else "unknown"
    bucket = f"auth:{client_ip}"
    limiter: SlidingWindowLimiter = request.app.state.auth_limiter

    if limiter.is_blocked(bucket):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Terlalu banyak percobaan gagal.",
            headers={"Retry-After": str(limiter.retry_after(bucket))},
        )

    if not verify_passcode(payload.passcode, config):
        limiter.record(bucket)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Passcode salah.",
            headers={"Retry-After": str(config.auth_window_seconds)},
        )

    limiter.clear(bucket)

    response.set_cookie(
        SESSION_COOKIE_NAME,
        request.app.state.session_store.issue(),
        max_age=config.session_ttl_seconds,
        httponly=True,
        samesite="lax",
        secure=config.debug is False,
        path="/",
    )
    return PasscodeResponse(ok=True, expires_in=config.session_ttl_seconds)


@public_router.post(
    "/auth/logout",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def logout(request: Request, response: Response) -> Response:
    """Cabut akses: hapus token dari daftar dan cookie di browser.

    Menghapus cookie saja tidak cukup. Kalau token tetap terdaftar, siapa pun
    yang masih memegang salinan token itu masih bisa memakai API langsung.

    Yang dikembalikan adalah ``Response`` **baru** yang membawa header dari
    objek yang diinjeksi. Dua alternatif sudah dicoba dan keduanya salah:
    mengembalikan objek yang diinjeksi langsung menghasilkan respons tanpa
    status (FastAPI berhenti mengirim body 204 tapi tidak pernah menulis
    ``status_code``, jadi klien menerima ``None``), sedangkan ``Response``
    kosong menghilangkan header ``set-cookie`` sehingga cookie tidak pernah
    terhapus di browser dan logout hanya berlaku di sisi server.
    """
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if token:
        request.app.state.session_store.revoke(token)
    response.delete_cookie(SESSION_COOKIE_NAME, path="/")
    return Response(
        status_code=status.HTTP_204_NO_CONTENT, headers=dict(response.headers)
    )


# -------------------------------------------------------------- documents


@router.get("/documents", response_model=list[DocumentSummary])
async def list_documents(repository: RepositoryDep) -> list[DocumentSummary]:
    return [document_to_summary(item) for item in repository.list_documents()]


@router.post(
    "/documents/upload",
    response_model=DocumentSummary,
    status_code=status.HTTP_202_ACCEPTED,
)
async def upload_document(
    file: Annotated[UploadFile, File()],
    ingestion: IngestionDep,
    config: SettingsDep,
) -> DocumentSummary:
    """Terima berkas lalu mulai ingestion (FR-1.1).

    ``202`` karena ingestion berjalan di background. Endpoint ini sengaja tidak
    menunggu sampai ``ready``: embedding satu dokumen bisa memakan puluhan
    detik, dan frontend sudah punya polling status (FR-1.4).
    """
    # Nama yang hanya berisi spasi diperlakukan sama dengan nama kosong.
    # Tanpa ini, `file.filename or "dokumen"` diam-diam menamai berkas
    # "dokumen" dan pengguna tidak pernah tahu nama aslinya hilang.
    filename = (file.filename or "").strip()
    if not filename:
        raise HTTPException(status_code=400, detail="Nama berkas tidak terbaca.")

    data = await file.read()
    # Ukuran dicek sebelum parsing. Menolak lebih awal menghemat pekerjaan
    # dan tidak membiarkan memori terisi berkas yang memang akan ditolak.
    if len(data) > config.max_file_size_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=(
                f"Berkas terlalu besar. Maksimal "
                f"{config.max_file_size_bytes // (1024 * 1024)} MB."
            ),
        )

    document = await ingestion.register(filename, data)
    logger.info(
        "Dokumen %s diterima: status=%s ukuran=%d byte",
        document.id,
        document.status.value,
        document.size_bytes,
    )
    return document_to_summary(document)


@router.get("/documents/{document_id}", response_model=DocumentDetail)
async def get_document(
    document_id: str,
    repository: RepositoryDep,
    config: SettingsDep,
    ingestion: IngestionDep,
) -> DocumentDetail:
    """Metadata dokumen dan konfigurasi ingestion. Tanpa daftar chunk."""
    document = repository.get_document(document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Dokumen tidak ditemukan.")

    return document_to_detail(
        document,
        IngestionInfo(
            splitter="Paragraf-Kalimat-BatasKarakter",
            chunk_size=config.chunk_size,
            chunk_overlap=config.chunk_overlap,
            embedding_model=config.embedding_model,
            # Nama store dibaca dari instance yang benar-benar dipakai.
            # Hardcode ``chroma`` pernah membuat halaman detail menampilkan
            # Chroma padahal yang aktif adalah store in-memory.
            vector_store=ingestion.store.name,
        ),
    )


@router.get("/documents/{document_id}/status", response_model=DocumentStatusResponse)
async def get_document_status(
    document_id: str, repository: RepositoryDep
) -> DocumentStatusResponse:
    document = repository.get_document(document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Dokumen tidak ditemukan.")
    return DocumentStatusResponse(
        id=document.id,
        status=document.status,
        chunk_count=document.chunk_count,
        error_message=document.error_message,
    )


@router.get("/documents/{document_id}/chunks", response_model=ChunkPage)
async def get_document_chunks(
    document_id: str,
    repository: RepositoryDep,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 10,
    q: Annotated[str | None, Query(max_length=200)] = None,
) -> ChunkPage:
    """Satu halaman chunk dengan pencarian isi (FR-5.1).

    ``total`` dihitung **setelah** filter, karena frontend memakainya untuk
    menghitung jumlah halaman.
    """
    if repository.get_document(document_id) is None:
        raise HTTPException(status_code=404, detail="Dokumen tidak ditemukan.")

    chunks, total = await asyncio.to_thread(
        repository.get_chunks, document_id, page, page_size, q
    )
    return ChunkPage(
        items=[chunk_to_response(chunk) for chunk in chunks],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.delete(
    "/documents/{document_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_document(
    document_id: str, ingestion: IngestionDep, repository: RepositoryDep
) -> Response:
    """Hapus dokumen, chunk-nya, dan indeksnya (FR-1.5)."""
    if repository.get_document(document_id) is None:
        raise HTTPException(status_code=404, detail="Dokumen tidak ditemukan.")
    await ingestion.delete(document_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ------------------------------------------------------------------- chat


@router.post("/chat/query")
async def chat_query(
    payload: ChatQueryRequest,
    rag: RagDep,
    limiter: LimiterDep,
) -> StreamingResponse:
    """Tanya pertanyaan, jawaban di-stream sebagai SSE (FR-2.4).

    Rate limit per sesi melindungi kuota free tier. Pelanggaran dijawab ``429``
    plus header ``Retry-After``, yang dipakai frontend untuk hitung mundur.
    """
    allowed, retry_after = await limiter.check(payload.session_id or "anon")
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Terlalu banyak permintaan. Coba lagi sebentar lagi.",
            headers={"Retry-After": str(retry_after)},
        )

    async def event_stream() -> AsyncIterator[bytes]:
        # Komentar SSE sebagai pembuka: beberapa proxy menahan respons sampai
        # byte pertama masuk, dan ini memastikan koneksi langsung ter flushing.
        yield b": stream dimulai\n\n"
        try:
            async for event in rag.answer(
                question=payload.question,
                session_id=payload.session_id,
                document_ids=payload.document_ids,
            ):
                data = json.dumps(event.to_payload(), ensure_ascii=False)
                yield f"data: {data}\n\n".encode()
        except Exception:  # noqa: BLE001
            logger.exception("Stream chat gagal")
            error = json.dumps(
                {"type": "error", "message": "Terjadi kesalahan saat memproses pertanyaan."},
                ensure_ascii=False,
            )
            yield f"data: {error}\n\n".encode()
            return
        yield b"data: [DONE]\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            # nginx menahan respons secara default; tanpa header ini stream
            # terkirim utuh di akhir, bukan sedikit demi sedikit.
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/chat/sessions", response_model=list[dict[str, object]])
async def list_sessions(repository: RepositoryDep, rag: RagDep) -> list[dict[str, object]]:
    """Sesi yang masih hidup di memory store, terbaru lebih dulu.

    Hanya sesi yang masih ada di memory store yang dikembalikan, karena itu
    yang benar-benar bisa dibuka lagi. Sesi yang sudah kedaluwarsa tidak
    muncul, dan frontend menampilkan daftar kosong, bukan error.
    """
    alive = set(await rag.live_session_ids())
    sessions = [item for item in repository.list_sessions() if item.id in alive]
    return [session_to_response(item).model_dump() for item in sessions]


@router.delete(
    "/chat/sessions",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_all_sessions(rag: RagDep) -> Response:
    """Hapus seluruh sesi (FR-6.3).

    Berbeda dari ``DELETE /chat/sessions/{id}`` yang hanya satu sesi.
    """
    await rag.delete_all_sessions()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.patch("/chat/sessions/{session_id}", response_model=dict[str, object])
async def rename_session(
    session_id: str,
    payload: SessionRenameRequest,
    repository: RepositoryDep,
) -> dict[str, object]:
    """Ubah judul satu percakapan.

    Judul hasil otomatis hanya dipakai sampai pengguna memberi nama sendiri.
    Kalau tidak begitu, pertanyaan berikutnya akan menimpa nama itu dan
    pengguna akan menemukan namanya berubah sendiri.
    """
    if repository.get_session(session_id) is None:
        raise HTTPException(status_code=404, detail="Sesi tidak ditemukan.")

    repository.rename_session(session_id, payload.title)
    updated = repository.get_session(session_id)
    if updated is None:
        raise HTTPException(status_code=404, detail="Sesi tidak ditemukan.")
    return session_to_response(updated).model_dump()


@router.delete(
    "/chat/sessions/{session_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_session(
    session_id: str, repository: RepositoryDep, rag: RagDep
) -> Response:
    """Hapus satu percakapan beserta pesanannya."""
    if repository.get_session(session_id) is None:
        raise HTTPException(status_code=404, detail="Sesi tidak ditemukan.")
    await rag.delete_session(session_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/chat/{session_id}/history", response_model=ChatHistoryResponse)
async def get_history(
    session_id: str, repository: RepositoryDep, rag: RagDep
) -> ChatHistoryResponse:
    """Riwayat percakapan satu sesi.

    ``404`` kalau sesi tidak ada atau sudah kedaluwarsa, supaya frontend bisa
    membedakan "hilang" dari "server gagal".
    """
    session = repository.get_session(session_id)
    if session is None:
        raise HTTPException(
            status_code=404, detail="Sesi tidak ditemukan atau sudah berakhir."
        )

    messages = await rag.get_history(session_id)
    return ChatHistoryResponse(
        session=session_to_response(session),
        messages=[message_to_response(message) for message in messages],
    )


@router.delete(
    "/chat/{session_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_session_by_path(
    session_id: str, repository: RepositoryDep, rag: RagDep
) -> Response:
    """Hapus satu percakapan lewat ``/chat/{id}``.

    Alias dari ``DELETE /chat/sessions/{id}``. PRD menyebut bentuk kedua,
    sementara sidebar memakai bentuk pertama; keduanya disediakan supaya
    kontrak lama dan baru sama-sama bekerja.
    """
    if repository.get_session(session_id) is None:
        raise HTTPException(status_code=404, detail="Sesi tidak ditemukan.")
    await rag.delete_session(session_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --------------------------------------------------------------- settings


@router.get("/settings", response_model=SettingsResponse)
async def get_retrieval_settings(repository: RepositoryDep) -> SettingsResponse:
    """Parameter retrieval yang sedang aktif (FR-6.1)."""
    current = await asyncio.to_thread(repository.get_settings)
    return SettingsResponse(
        top_k=current.top_k, similarity_threshold=current.similarity_threshold
    )


@router.put("/settings", response_model=SettingsResponse)
async def update_retrieval_settings(
    payload: SettingsUpdate, repository: RepositoryDep, config: SettingsDep
) -> SettingsResponse:
    """Ubah parameter retrieval (FR-6.2).

    Nilai diklem ke rentang yang diizinkan. Response mengembalikan nilai final
    yang aktif, jadi frontend tidak perlu menebak apa yang terjadi kalau clamping
    terjadi.
    """
    patch: dict[str, object] = {}
    if payload.top_k is not None:
        patch["top_k"] = max(config.min_top_k, min(config.max_top_k, payload.top_k))
    if payload.similarity_threshold is not None:
        patch["similarity_threshold"] = max(
            config.min_similarity_threshold,
            min(config.max_similarity_threshold, payload.similarity_threshold),
        )

    updated = await asyncio.to_thread(repository.update_settings, patch)
    return SettingsResponse(
        top_k=updated.top_k, similarity_threshold=updated.similarity_threshold
    )


# -------------------------------------------------------------- analytics


@router.get("/analytics/summary", response_model=AnalyticsSummaryResponse)
async def get_analytics_summary(repository: RepositoryDep) -> AnalyticsSummaryResponse:
    """Skor RAGAS terbaru, tren latensi, dan konsumsi token (FR-7.3).

    ``latest_eval`` bernilai ``None`` kalau belum ada run evaluasi, dan frontend
    menampilkan empty state. Tidak ada angka placeholder di sini.
    """
    latest = repository.latest_eval()
    latency = await asyncio.to_thread(repository.latency_by_day, 14)
    tokens = await asyncio.to_thread(repository.tokens_by_day, 14)

    return AnalyticsSummaryResponse(
        latest_eval=(
            EvalRunResponse(
                id=str(latest["id"]),
                precision=_as_float(latest.get("precision")),
                faithfulness=_as_float(latest.get("faithfulness")),
                answer_relevance=_as_float(latest.get("answer_relevance")),
                run_at=str(latest["run_at"]),
            )
            if latest
            else None
        ),
        latency=[LatencyPoint(**point) for point in latency],  # type: ignore[arg-type]
        tokens=[TokenPoint(**point) for point in tokens],  # type: ignore[arg-type]
    )


@router.get("/analytics/logs", response_model=AnalyticsLogsResponse)
async def get_analytics_logs(
    repository: RepositoryDep,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 10,
) -> AnalyticsLogsResponse:
    """Log query terakhir, terpaginasi (FR-7.2)."""
    logs, total = await asyncio.to_thread(repository.list_logs, page, page_size)
    return AnalyticsLogsResponse(
        items=[log_to_response(log) for log in logs],
        total=total,
        page=page,
        page_size=page_size,
    )


# ----------------------------------------------------------------- health


@public_router.get("/health", response_model=HealthResponse)
async def health(
    repository: RepositoryDep,
    rag: RagDep,
    ingestion: IngestionDep,
    config: SettingsDep,
) -> HealthResponse:
    """Health check untuk monitoring.

    Tidak memanggil LLM, karena endpoint ini dipakai monitor dan harus
    menjawab cepat. Status LLM berdasarkan provider yang benar-benar
    terkonfigurasi, bukan berdasarkan panggilan jaringan.

    Setiap komponen di-ping sendiri. Versi sebelumnya memakai
    ``repository.ping()`` untuk menentukan status vector store, yang membuat
    vector store mati tapi metadata sehat dilaporkan ``ok``.
    """
    llm_status: Literal["ok", "unreachable"] = "ok" if rag.provider_names else "unreachable"
    memory_ok = await rag.memory_available()
    repository_ok = await asyncio.to_thread(repository.ping)
    vector_ok = await asyncio.to_thread(ingestion.store.ping)

    from app.dependencies import get_tracer  # noqa: PLC0415

    tracing_on = get_tracer().enabled

    components_ok = llm_status == "ok" and memory_ok and repository_ok and vector_ok

    return HealthResponse(
        # Store in-memory memang tidak persisten, dan itu dilaporkan lewat
        # ``vector_store`` plus mode di bawah, bukan disembunyikan dengan
        # jawaban ``ok`` yang menyesatkan.
        status="ok" if components_ok else "degraded",
        llm=llm_status,
        vector_store="ok" if vector_ok else "unreachable",
        memory="ok" if memory_ok else "unreachable",
        version=config.version,
        # Mode fallback yang sedang aktif, supaya operator tidak salah
        # mengira data sudah persisten padahal belum. Tracing ikut
        # dilaporkan agar kolom Trace di /analytics bisa menjelaskan kenapa
        # kosong: bukan error, memang dimatikan.
        fallback={
            "repository": repository.name,
            "memory": rag.memory.name,
            "vector_store": ingestion.store.name,
            "vector_store_persistent": ingestion.store.persistent,
            "tracing": tracing_on,
            "mode": "full" if components_ok and ingestion.store.persistent else "reduced",
        },
    )


def _as_float(value: object) -> float | None:
    """Konversi aman ke float, untuk kolom yang boleh NULL."""
    if value is None:
        return None
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
