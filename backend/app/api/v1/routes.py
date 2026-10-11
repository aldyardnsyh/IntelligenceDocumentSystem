"""Route API v1.

Semua handler mengikuti aturan yang sama: kalau ada yang gagal, pesan error
ditulis untuk dibaca orang, bukan exception mentah. Bentuk error seragam ada
di ``app.main`` lewat exception handler.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from collections.abc import AsyncIterator
from pathlib import Path
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
from app.core.security import (
    SESSION_COOKIE_NAME,
    SlidingWindowLimiter,
    owner_of_token,
    verify_passcode,
)
from app.dependencies import (
    get_app_settings,
    get_ingestion,
    get_rag,
    get_rate_limiter,
    get_repository,
)
from app.models.domain import DocumentStatus
from app.models.schemas import (
    AnalyticsLogsResponse,
    AnalyticsSummaryResponse,
    ChatHistoryResponse,
    ChatQueryRequest,
    ChunkPage,
    DocumentDetail,
    DocumentPreviewResponse,
    DocumentStatusResponse,
    DocumentSummary,
    EvalRequest,
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
from app.repositories.sqlite_repo import MetadataRepository, new_id, utc_now
from app.services.evaluation import (
    RetrievalEvalItem,
    RetrievalEvalReport,
    expected_document,
    expects_refusal,
    load_dataset,
)
from app.services.ingestion.parser import ParseError, sanitize_filename, validate_extension
from app.services.ingestion.service import IngestionService
from app.services.memory.rate_limit import RateLimiter
from app.services.rag_service import RagService

logger = logging.getLogger(__name__)

#: Ruang tambahan untuk Amplop multipart (boundary, header part). Dipakai
#: saat membandingkan ``Content-Length`` dengan batas berkas.
_UPLOAD_OVERHEAD_BYTES = 8 * 1024

#: Batas jumlah chunk yang disusun menjadi pratinjau dokumen. Cukup untuk
#: membaca isi dokumen biasa, dan menjaga respons tetap wajar ukurannya
#: kalau ada dokumen yang sangat panjang.
_PREVIEW_MAX_CHUNKS = 500

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
    # Identitas pemilik disimpan di state request. Handler memakainya untuk
    # rate limit dan pengecekan kepemilikan sesi, sehingga tidak ada satu pun
    # endpoint yang pakai nilai yang dikirim klien sebagai identitas.
    request.state.auth_owner = token


def client_ip(request: Request, config: Settings) -> str:
    """IP klien untuk key rate limit.

    Yang dikembalikan adalah `request.client.host`, yang oleh uvicorn sudah
    merupakan IP asli kalau header proxy tepercaya diizinkan
    (`--forwarded-allow-ips`). Header `X-Forwarded-For` sengaja tidak
    diuraikan sendiri di sini: elemen paling kiri adalah nilai yang bisa
    dikendalikan klien, dan membacanya secara manual justru membuka jalan
    untuk menyusun ulang bucket rate limit sesuka hati.

    Dibalik proxy tanpa `--proxy-headers`, hasilnya adalah IP proxy, satu
    bucket untuk semua pengguna. Itu memang konsekuensi yang harus
    dipahami operator, bukan sesuatu yang bisa ditutup dengan parsing header
    yang keliru.
    """
    return request.client.host if request.client else "unknown"


def _assert_session_owner(request: Request, session_id: str) -> None:
    """Tolak akses ke percakapan milik identitas lain.

    ``session_id`` adalah tebakan yang dikirim klien, jadi keberadaan sesi
    saja tidak membuktikan kepemilikan. Tanpa pemeriksaan ini, siapa pun yang
    memegang cookie sah bisa membaca, mengganti nama, atau menghapus
    percakapan orang lain hanya dengan menebak id.
    """
    owner: str = getattr(request.state, "auth_owner", "")
    if not request.app.state.session_store.may_access_session(session_id, owner):
        raise HTTPException(status_code=403, detail="Sesi ini bukan milik Anda.")


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
    bucket = f"auth:{client_ip(request, config)}"
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
            # Sisa jendela sebenarnya, bukan konfigurasi statis: klien yang
            # benar-benar melihat countdown harus tahu kapan bisa mencoba lagi.
            headers={"Retry-After": str(limiter.retry_after(bucket))},
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
    request: Request,
    file: Annotated[UploadFile, File()],
    ingestion: IngestionDep,
    config: SettingsDep,
) -> DocumentSummary:
    """Terima berkas lalu mulai ingestion (FR-1.1).

    ``202`` karena ingestion berjalan di background. Endpoint ini sengaja tidak
    menunggu sampai ``ready``: embedding satu dokumen bisa memakan puluhan
    detik, dan frontend sudah punya polling status (FR-1.4).

    Yang tetap dilakukan sebelum ``202``: sanitasi nama, cek ukuran saat
    dibaca (bukan sesudahnya), dan cek format. Semua itu murah, dan
    kegagalan di sini lebih jujur daripada dokumen yang gagal diam-diam di
    background lalu baru muncul saat polling.
    """
    # Nama yang hanya berisi spasi diperlakukan sama dengan nama kosong.
    # Tanpa ini, `file.filename or "dokumen"` diam-diam menamai berkas
    # "dokumen" dan pengguna tidak pernah tahu nama aslinya hilang.
    try:
        filename = sanitize_filename(file.filename or "")
    except ParseError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    try:
        validate_extension(filename, config)
    except ParseError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    # Header content-length diperiksa sebelum body apa pun diproses. Parser
    # multipart milik framework sudah menelan dan men-spool seluruh request
    # ke disk sebelum handler ini jalan, sehingga `_read_limited` hanya
    # membatasi salinan di memori, bukan yang tersimpan di disk.
    declared = request.headers.get("content-length")
    if (
        declared
        and declared.isdigit()
        and int(declared) > config.max_file_size_bytes + _UPLOAD_OVERHEAD_BYTES
    ):
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=(
                "Berkas terlalu besar. Maksimal "
                f"{config.max_file_size_bytes // (1024 * 1024)} MB."
            ),
        )

    data = await _read_limited(file, config.max_file_size_bytes)
    document = await ingestion.register(filename, data)

    # `register` sudah mem-parse berkas sebelum mengembalikan dokumen. Kalau
    # parsing gagal, jawabannya bukan "sedang diproses" melainkan "gagal":
    # mengembalikan 202 untuk berkas yang sudah ditolak membuat pengguna
    # menunggu status yang memang tidak akan pernah berubah.
    if document.status is DocumentStatus.FAILED:
        await asyncio.to_thread(ingestion.repository.delete_document, document.id)
        raise HTTPException(
            status_code=400,
            detail=document.error_message or "Berkas tidak bisa dibaca.",
        )

    logger.info(
        "Dokumen %s diterima: status=%s ukuran=%d byte",
        document.id,
        document.status.value,
        document.size_bytes,
    )
    return document_to_summary(document)


async def _read_limited(file: UploadFile, max_bytes: int) -> bytes:
    """Baca berkas bertahap, berhenti begitu melewati batas.

    ``await file.read()`` membaca seluruh body ke memori dulu; batas ukuran
    baru berlaku setelah memorinya terpakai. Klien yang mengirim body jauh
    melampaui batas bisa membuat satu worker menahan ratusan megabyte.
    """
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await file.read(1024 * 1024)
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=f"Berkas terlalu besar. Maksimal {max_bytes // (1024 * 1024)} MB.",
            )
        chunks.append(chunk)

    if total == 0:
        raise HTTPException(status_code=400, detail="Berkas kosong.")
    return b"".join(chunks)


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


@router.get("/documents/{document_id}/preview", response_model=DocumentPreviewResponse)
async def get_document_preview(
    document_id: str,
    repository: RepositoryDep,
) -> DocumentPreviewResponse:
    """Isi dokumen yang benar-benar tersimpan, untuk cross-check (FR-5.2).

    Halaman dokumen sebelumnya hanya menampilkan daftar chunk. Untuk menilai
    apakah jawaban chat benar, pengguna perlu melihat teks aslinya berurutan.
    Chunk terpisah-pisah menyembunyikan konteks di sekitarnya.

    Yang dikembalikan adalah teks hasil parsing (bukan berkas aslinya), jadi
    tidak ada berkas biner yang dikirim ke browser dan tidak ada risiko
    menjalankan konten pengguna.
    """
    document = await asyncio.to_thread(repository.get_document, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Dokumen tidak ditemukan.")

    chunks, total = await asyncio.to_thread(
        repository.get_chunks, document_id, 1, _PREVIEW_MAX_CHUNKS, None
    )
    if total == 0:
        raise HTTPException(
            status_code=409,
            detail=(
                "Dokumen ini belum punya isi yang bisa ditampilkan. "
                "Tunggu sampai ingestion selesai, atau periksa statusnya."
            ),
        )

    # Chunk disusun ulang sesuai urutan aslinya. `char_start` dipakai kalau
    # ada, supaya urutannya benar meski indeks chunk pernah dibangun ulang.
    ordered = sorted(chunks, key=lambda item: (item.char_start, item.chunk_index))
    text = "\n\n".join(chunk.content for chunk in ordered)

    return DocumentPreviewResponse(
        id=document.id,
        filename=document.filename,
        status=document.status,
        content=text,
        chunk_count=document.chunk_count,
        # Ditampilkan kalau isinya terpotong, supaya pengguna tahu yang
        # dibaca bukan keseluruhan dokumen.
        truncated=total > len(ordered),
        preview_chars=len(text),
        total_chars=sum(len(chunk.content) for chunk in ordered),
    )


@router.get("/documents/{document_id}/file")
async def get_document_file(
    document_id: str,
    ingestion: IngestionDep,
    repository: RepositoryDep,
) -> Response:
    """Berkas asli dokumen, untuk pratinjau PDF di browser (FR-5.2).

    Yang dikirim adalah berkas yang benar-benar diunggah pengguna, bukan
    render ulang dari teks. Halaman dokumen memakainya untuk menampilkan PDF
    berdampingan dengan chunk, sehingga ekstraksi teksnya bisa diperiksa
    langsung: tata letak, tabel, dan halaman yang gagal terbaca hanya
    terlihat di berkas aslinya.

    ``Content-Disposition: inline`` supaya browser menampilkan PDF-nya, bukan
    mengunduhnya. ``X-Content-Type-Options: nosniff`` mencegah browser
    menebak jenis konten lain dari isi berkas.
    """
    document = await asyncio.to_thread(repository.get_document, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Dokumen tidak ditemukan.")

    data = await asyncio.to_thread(
        ingestion.original_files.load, document_id, document.filename
    )
    if data is None:
        raise HTTPException(
            status_code=404,
            detail=(
                "Berkas asli dokumen ini tidak tersimpan, jadi pratinjau tidak "
                "tersedia. Isi teksnya tetap bisa dibaca di tab Pratinjau isi."
            ),
        )

    media_type = _media_type_for(document.filename)
    # Nama berkas di header dibersihkan: nilai dari klien tidak boleh masuk
    # ke header HTTP mentah.
    safe_name = re.sub(r'[^A-Za-z0-9._-]', "_", document.filename) or "dokumen"
    return Response(
        content=data,
        media_type=media_type,
        headers={
            "Content-Disposition": f'inline; filename="{safe_name}"',
            "X-Content-Type-Options": "nosniff",
            # Berkas dokumen pengguna tidak boleh di-cache bersama oleh proxy.
            "Cache-Control": "private, max-age=300",
        },
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
    request: Request,
    payload: ChatQueryRequest,
    rag: RagDep,
    limiter: LimiterDep,
    repository: RepositoryDep,
) -> StreamingResponse:
    """Tanya pertanyaan, jawaban di-stream sebagai SSE (FR-2.4).

    Rate limit melindungi kuota free tier. Kunci bucket diambil dari identitas
    akses yang sudah diverifikasi, bukan dari ``session_id`` di body: kalau
    kuncinya dari klien, setiap request dengan id acak mendapat bucket baru
    dan kuota tidak pernah tercapai. Sesi baru dari pengguna berbeda juga
    tidak lagi berbagi satu bucket bersama.
    """
    owner: str = request.state.auth_owner
    allowed, retry_after = await limiter.check(f"chat:{owner_of_token(owner)}")
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Terlalu banyak permintaan. Coba lagi sebentar lagi.",
            headers={"Retry-After": str(retry_after)},
        )

    # Percakapan diklaim pemiliknya baik sesi sudah ada maupun baru dibuat
    # sekarang. Kalau klaim hanya dilakukan untuk sesi yang sudah ada,
    # pertanyaan pertama membuat sesi tanpa pemilik, dan siapa pun yang tahu
    # id-nya bisa mengambil alih di request berikutnya.
    if payload.session_id and not request.app.state.session_store.claim_session(
        payload.session_id, owner
    ):
        raise HTTPException(status_code=403, detail="Sesi ini bukan milik Anda.")

    # Scope dokumen divalidasi lebih dulu. Sesi yang diikat ke dokumen yang
    # tidak ada (atau belum selesai diindeks) hanya akan mencari di ruang
    # kosong: setiap pertanyaan dijawab "tidak ditemukan" tanpa penjelasan,
    # dan pengguna mengira sistemnya rusak. Menolak di sini memberi pesan yang
    # bisa ditindaklanjuti.
    #
    # PENTING: sesi yang sudah punya scope mengikat dirinya sendiri. Nilai
    # dari request hanya dipakai saat sesi baru. Kalau tidak, klien yang lupa
    # mengirim `document_id` (mis. daftar sesi sedang dimuat ulang) akan
    # membuat pertanyaan lanjutan mencari di SELURUH dokumen, kebocoran
    # scope yang tidak terlihat di UI, dan persis yang membuat "chat privat
    # per dokumen" tidak bisa dipercaya.
    effective_document_id = payload.document_id
    if payload.session_id:
        stored_session = await asyncio.to_thread(
            repository.get_session, payload.session_id
        )
        if stored_session is not None and stored_session.document_id:
            effective_document_id = stored_session.document_id

    if effective_document_id is not None:
        scoped = await asyncio.to_thread(
            repository.get_document, effective_document_id
        )
        if scoped is None:
            raise HTTPException(
                status_code=404, detail="Dokumen yang ingin ditanyai tidak ditemukan."
            )
        if scoped.status is not DocumentStatus.READY:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Dokumen '{scoped.filename}' belum siap ditanyai "
                    f"(status: {scoped.status.value}). Tunggu sampai selesai diindeks."
                ),
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
                document_id=effective_document_id,
                allow_ungrounded=payload.allow_ungrounded,
            ):
                if event.type == "session":
                    # Sesi yang baru dibuat server (klien mengirim
                    # `session_id: null`) harus diklaim sekarang juga. Kalau
                    # tidak, sesi itu tetap tanpa pemilik dan siapa pun yang
                    # tahu id-nya bisa membacanya.
                    request.app.state.session_store.claim_session(
                        event.session_id, owner
                    )
                data = json.dumps(event.to_payload(), ensure_ascii=False)
                yield f"data: {data}\n\n".encode()
        except Exception:  # noqa: BLE001
            logger.exception("Stream chat gagal")
            # Provider yang gagal (kuota habis, jaringan) dibedakan dari bug
            # server supaya frontend bisa menampilkan aksi yang tepat:
            # menunggu versus mencoba ulang.
            error = json.dumps(
                {
                    "type": "error",
                    "message": "Terjadi kesalahan saat memproses pertanyaan.",
                    "retry_after_seconds": 30,
                },
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
async def delete_all_sessions(request: Request, rag: RagDep) -> Response:
    """Hapus seluruh sesi (FR-6.3).

    Klaim kepemilikan ikut dilepas: sisa klaim membuat id sesi lama tidak
    bisa diklaim ulang, dan pengguna yang baru mulai dari sesi kosong akan
    diblokir oleh sesinya sendiri.
    """
    await rag.delete_all_sessions()
    request.app.state.session_store.forget_owner_sessions(
        getattr(request.state, "auth_owner", "")
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.patch("/chat/sessions/{session_id}", response_model=dict[str, object])
async def rename_session(
    request: Request,
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
    _assert_session_owner(request, session_id)

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
    request: Request,
    session_id: str,
    repository: RepositoryDep,
    rag: RagDep,
) -> Response:
    """Hapus satu percakapan beserta pesanannya."""
    if repository.get_session(session_id) is None:
        raise HTTPException(status_code=404, detail="Sesi tidak ditemukan.")
    _assert_session_owner(request, session_id)
    request.app.state.session_store.forget_session(session_id)
    await rag.delete_session(session_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/chat/{session_id}/history", response_model=ChatHistoryResponse)
async def get_history(
    request: Request,
    session_id: str,
    repository: RepositoryDep,
    rag: RagDep,
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
    _assert_session_owner(request, session_id)

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
    request: Request,
    session_id: str,
    repository: RepositoryDep,
    rag: RagDep,
) -> Response:
    """Hapus satu percakapan lewat ``/chat/{id}``.

    Alias dari ``DELETE /chat/sessions/{id}``. PRD menyebut bentuk kedua,
    sementara sidebar memakai bentuk pertama; keduanya disediakan supaya
    kontrak lama dan baru sama-sama bekerja.
    """
    if repository.get_session(session_id) is None:
        raise HTTPException(status_code=404, detail="Sesi tidak ditemukan.")
    _assert_session_owner(request, session_id)
    request.app.state.session_store.forget_session(session_id)
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
    latest = await asyncio.to_thread(repository.latest_eval)
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


@router.post("/analytics/evaluate", response_model=EvalRunResponse)
async def run_retrieval_evaluation(
    rag: RagDep,
    repository: RepositoryDep,
    config: SettingsDep,
    payload: EvalRequest | None = None,
) -> EvalRunResponse:
    """Jalankan evaluasi retrieval tanpa LLM dan tanpa API key (FR-7.3).

    Halaman /analytics sebelumnya hanya bisa diisi oleh skrip RAGAS, yang
    butuh LLM penilai dan kredensial tambahan. Tanpa itu, pengguna melihat
    "belum ada data evaluasi" tanpa jalan keluar, diberi tahu ada yang
    kurang, tapi tidak ada cara memenuhinya.

    Endpoint ini menghitung metrik yang bisa dijawab tanpa model: berapa
    persen pertanyaan menemukan sumbernya, seberapa tepat sumber yang
    diambil, dan berapa pertanyaan "tidak ada jawaban" yang benar ditolak.
    Hasilnya disimpan ke tabel yang sama dengan RAGAS, jadi halaman analitik
    langsung terisi.
    """
    dataset_path = Path(config.evaluation_dataset_path)
    if not dataset_path.exists():
        raise HTTPException(
            status_code=409,
            detail=(
                f"Dataset evaluasi tidak ditemukan di {dataset_path}. "
                "Jalankan evaluasi lewat CLI, atau sediakan berkasnya."
            ),
        )

    try:
        dataset = await asyncio.to_thread(load_dataset, dataset_path)
    except (ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=422, detail=f"Dataset tidak valid: {exc}") from exc

    documents = await asyncio.to_thread(repository.list_documents)
    available = {document.filename for document in documents}
    by_id = {document.id: document for document in documents}

    # Mode "dokumen pilihan": pengguna memilih dokumen di UI, dan pertanyaan
    # dataset dijalankan terhadap dokumen itu saja. Ini yang membuat evaluasi
    # berguna untuk korpus sendiri, dataset bawaan hanya cocok untuk
    # dokumen contoh.
    scoped_ids: list[str] | None = None
    if payload is not None and payload.document_ids:
        unknown = [item for item in payload.document_ids if item not in by_id]
        if unknown:
            raise HTTPException(
                status_code=404,
                detail=(
                    "Dokumen yang dipilih tidak ditemukan: "
                    f"{', '.join(unknown)}. Muat ulang halaman lalu pilih lagi."
                ),
            )
        not_ready = [
            by_id[item].filename
            for item in payload.document_ids
            if by_id[item].status is not DocumentStatus.READY
        ]
        if not_ready:
            raise HTTPException(
                status_code=409,
                detail=(
                    "Dokumen berikut belum siap diuji: "
                    f"{', '.join(not_ready)}. Tunggu sampai selesai diindeks."
                ),
            )
        scoped_ids = list(payload.document_ids)

        # Semua pertanyaan dataset tetap dijalankan. Nama dokumen di dataset
        # TIDAK dipakai untuk menyaring: yang diukur di mode ini adalah
        # "apakah retrieval menemukan sumber di dokumen yang dipilih", bukan
        # "apakah namanya sama dengan dokumen contoh".
        #
        # Menyaring berdasarkan nama akan membuat fitur ini tidak berguna
        # untuk korpus sendiri: dokumen pengguna tidak akan pernah bernama
        # seperti dokumen contoh, dan seluruh pertanyaan ikut terbuang.
        #
        # Konsekuensinya: pertanyaan yang isinya memang tidak ada di dokumen
        # pilihan akan dihitung sebagai "tidak menemukan sumber". Itu benar,
        # karena retrieval-nya memang tidak menemukan apa pun di korpus itu.
    else:
        # Dataset merujuk dokumen tertentu. Kalau dokumennya tidak ada di
        # korpus, skornya akan nol, dan nol tanpa penjelasan terbaca sebagai
        # "retrieval rusak", padahal dokumennya memang belum ada.
        wanted = {
            expected_document(entry)
            for entry in dataset
            if expected_document(entry) is not None
        }
        missing = sorted(name for name in wanted if name not in available)
        if wanted and len(missing) == len(wanted):
            raise HTTPException(
                status_code=409,
                detail=(
                    "Dokumen yang dirujuk dataset evaluasi belum ada di korpus: "
                    f"{', '.join(missing)}. Unggah dokumen itu dulu, atau jalankan "
                    "`python -m scripts.seed_demo` yang membuat dokumen contoh "
                    "sesuai dataset. Anda juga bisa memilih dokumen sendiri di "
                    "halaman ini."
                ),
            )

    settings_row = await asyncio.to_thread(repository.get_settings)
    report = RetrievalEvalReport()

    for entry in dataset:
        question = str(entry["question"])
        target = expected_document(entry)
        must_refuse = expects_refusal(entry)

        retrieved = await rag.retrieve(question, settings_row, scoped_ids)
        names = [item.document_name for item in retrieved]

        # Pada mode dokumen pilihan, yang dinilai adalah "apakah retrieval
        # menemukan sumber di dokumen yang dipilih", bukan apakah namanya
        # sama dengan dokumen di dataset.
        if scoped_ids is not None:
            # Di mode dokumen pilihan, yang dinilai: apakah retrieval
            # menemukan sumber di korpus itu. Nama dokumennya bisa salah satu
            # dari yang dipilih, jadi tidak dibandingkan dengan satu nama.
            found = bool(retrieved)
            target = None
        else:
            found = bool(retrieved) if target is None else target in names

        report.items.append(
            RetrievalEvalItem(
                question=question,
                expected_document=target,
                retrieved_documents=names,
                found=found,
                refused=not retrieved,
                expected_refusal=must_refuse,
            )
        )

    summary = report.summary()
    run_id = new_id("eval")
    run_at = utc_now()

    # Kolom yang tersedia di tabel: precision, faithfulness, answer_relevance.
    # Metrik retrieval dipetakan ke kolom yang ada, dan yang tidak punya kolom
    # (hit_rate, refusal_rate) dilaporkan di log supaya tetap terlihat.
    await asyncio.to_thread(
        repository.add_eval_run,
        {
            "id": run_id,
            "run_at": run_at,
            "precision": summary["precision"],
            # Faithfulness hanya bisa dinilai LLM; dikosongkan, bukan diisi
            # angka tebakan.
            "faithfulness": None,
            # Hit rate dipakai sebagai proksi relevansi jawaban pada evaluasi
            # tanpa LLM: pertanyaan yang tidak menemukan sumbernya jelas tidak
            # bisa dijawab dengan relevan.
            "answer_relevance": summary["hit_rate"],
        },
    )

    logger.info(
        "Evaluasi retrieval selesai: hit_rate=%.2f precision=%.2f "
        "refusal_rate=%.2f (leaked=%d)",
        summary["hit_rate"],
        summary["precision"],
        summary["refusal_rate"],
        summary["leaked"],
    )

    return EvalRunResponse(
        id=run_id,
        precision=summary["precision"],  # type: ignore[arg-type]
        faithfulness=None,
        answer_relevance=summary["hit_rate"],  # type: ignore[arg-type]
        run_at=run_at,
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
    request: Request,
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

    # Provider mock dijawab "ok" selama namanya terdaftar, padahal tidak ada LLM
    # yang dipakai sama sekali. Mode provisioning bisa terlihat sehat sementara
    # semua jawaban bukan sintesis, jadi dipakai apa adanya di laporan.
    llm_is_mock = "mock" in rag.provider_names
    # Embedding hashing hanya cocok untuk token identik. Kalau diam-diam aktif,
    # kualitas retrieval anjlok dan ini harus terlihat di health.
    embedding_is_fallback = getattr(ingestion.embedding, "name", "") == "hashing-fallback"

    components_ok = (
        llm_status == "ok"
        and memory_ok
        and repository_ok
        and vector_ok
        and not embedding_is_fallback
    )

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
            "embedding": ingestion.embedding.name,
            "embedding_model": config.embedding_model,
            "llm": ",".join(rag.provider_names),
            "mode": (
                "full"
                if components_ok and ingestion.store.persistent and not llm_is_mock
                else "reduced"
            ),
            # Penanda proses ini. Berubah setiap kali backend dijalankan ulang.
            # Frontend memakainya untuk membuang state browser yang tersisa
            # dari proses sebelumnya: sesi akses dan riwayat percakapan hidup
            # di memori, jadi setelah restart semuanya sudah tidak berlaku.
            "boot_id": getattr(request.app.state, "boot_id", ""),
        },
    )


def _media_type_for(filename: str) -> str:
    """Jenis konten untuk pratinjau berkas asli.

    Hanya PDF yang punya jalur ini (lihat ``STORED_SUFFIXES`` di
    ``app/services/storage.py``). Selain itu dikirim sebagai teks biasa,
    bukan ditebak-tebak, supaya browser tidak pernah merender isi dokumen
    sebagai HTML.
    """
    suffix = Path(filename).suffix.lower()
    if suffix == ".pdf":
        return "application/pdf"
    if suffix in {".md", ".markdown"}:
        return "text/markdown; charset=utf-8"
    return "text/plain; charset=utf-8"


def _as_float(value: object) -> float | None:
    """Konversi aman ke float, untuk kolom yang boleh NULL."""
    if value is None:
        return None
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
