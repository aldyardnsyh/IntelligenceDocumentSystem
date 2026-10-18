"""Supabase REST repository.

Dipakai kalau ``SUPABASE_URL`` dan ``SUPABASE_SERVICE_KEY`` diisi. Akses lewat
REST PostgREST, bukan koneksi Postgres langsung, karena dua alasan praktis:

1. Port 5432 sering diblokir jaringan lokal, sementara HTTPS selalu terbuka.
2. Supabase free-tier project bisa di-pause, dan koneksi pool yang tersisa
   akan gagal diam-diam. REST lebih mudah dideteksi dan di-report.

Skema tabel harus dibuat lewat SQL editor Supabase atau file
``supabase/schema.sql``.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from typing import Any

import httpx

from app.core.config import Settings
from app.models.domain import (
    ChatSession,
    Document,
    DocumentStatus,
    QueryLog,
    RetrievalSettings,
)
from app.repositories.sqlite_repo import new_id, utc_now

logger = logging.getLogger(__name__)


def _total_from_content_range(header: str | None) -> int:
    """Ambil total baris dari header ``content-range`` PostgREST.

    Formatnya ``0-9/42``: bagian sebelum ``/`` adalah rentang baris yang
    dikembalikan, bagian sesudahnya adalah total. Kalau ujungnya ``*``,
    totalnya tidak diketahui dan dikembalikan ``0`` supaya frontend tidak
    menampilkan jumlah halaman yang pasti salah.
    """
    if not header or "/" not in header:
        return 0
    _, _, total = header.rpartition("/")
    if total == "*":
        return 0
    try:
        return int(total)
    except ValueError:
        return 0

TABLES = (
    "documents",
    "chunks",
    "sessions",
    "app_settings",
    "query_logs",
    "eval_runs",
)


class SupabaseRepository:
    """Metadata di Supabase lewat PostgREST."""

    name = "supabase"

    def __init__(self, settings: Settings) -> None:
        self._base_url = f"{settings.supabase_url}/rest/v1"
        self._headers = {
            "apikey": settings.supabase_service_key or "",
            "Authorization": f"Bearer {settings.supabase_service_key}",
            "Content-Type": "application/json",
        }
        self._timeout = 15.0

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, str] | None = None,
        json_body: object | None = None,
        headers: dict[str, str] | None = None,
        want_range_count: bool = False,
    ) -> Any:
        """Kirim request ke PostgREST.

        ``want_range_count`` mengembalikan objek ``(body, total)``. Hitungan
        total diambil dari header ``content-range``, satu-satunya tempat
        PostgREST menaruh total saat memakai ``Prefer: count=exact``.

        Versi sebelumnya melakukan request ``HEAD`` lalu mencoba membaca body
        sebagai JSON. Request ``HEAD`` memang tidak punya body, jadi ``total``
        selalu ``0``. Akibatnya paginasi di halaman detail dokumen selalu
        melaporkan satu halaman kosong padahal isinya ada.
        """
        request_headers = dict(self._headers)
        if want_range_count:
            request_headers["Prefer"] = "count=exact"

        response = httpx.request(
            method,
            f"{self._base_url}/{path}",
            headers=request_headers,
            params=params,
            json=json_body,
            timeout=self._timeout,
        )
        if response.status_code >= 400:
            raise RuntimeError(
                f"Supabase {method} {path} gagal: {response.status_code} {response.text[:200]}"
            )

        total = _total_from_content_range(response.headers.get("content-range"))
        if want_range_count:
            body = None
            if response.content:
                body = response.json()
            return body, total
        if response.status_code == 204 or not response.content:
            return None
        return response.json()

    # ------------------------------------------------------------ documents
    def add_document(self, document: Document) -> None:
        self._request(
            "POST",
            "documents",
            params={"on_conflict": "id"},
            json_body={
                "id": document.id,
                "filename": document.filename,
                "size_bytes": document.size_bytes,
                "status": document.status.value,
                "uploaded_at": document.uploaded_at,
                "page_count": document.page_count,
                "chunk_count": document.chunk_count,
                "error_message": document.error_message,
            },
        )

    def get_document(self, document_id: str) -> Document | None:
        rows = self._request(
            "GET", "documents", params={"id": f"eq.{document_id}", "limit": "1"}
        )
        return _to_document(rows[0]) if rows else None

    def list_documents(self) -> list[Document]:
        rows = self._request("GET", "documents", params={"order": "uploaded_at.desc"})
        return [_to_document(row) for row in rows or []]

    def update_document(self, document_id: str, **changes: object) -> None:
        payload = dict(changes)
        if isinstance(payload.get("status"), DocumentStatus):
            payload["status"] = payload["status"].value
        if not payload:
            return
        self._request("PATCH", "documents", params={"id": f"eq.{document_id}"}, json_body=payload)

    def delete_document(self, document_id: str) -> None:
        self._request("DELETE", "documents", params={"id": f"eq.{document_id}"})
        self.delete_chunks(document_id)

    # --------------------------------------------------------------- chunks
    def add_chunks(self, chunks: Iterable[object], document_id: str) -> None:
        rows = [
            {
                "id": chunk.id,
                "document_id": document_id,
                "chunk_index": chunk.chunk_index,
                "content": chunk.content,
                "page_number": chunk.page_number,
                "token_count": chunk.token_count,
                "char_start": getattr(chunk, "char_start", 0),
                "char_end": getattr(chunk, "char_end", 0),
            }
            for chunk in chunks
        ]
        for start in range(0, len(rows), 200):
            self._request(
                "POST",
                "chunks",
                params={"on_conflict": "id"},
                json_body=rows[start : start + 200],
            )

    def get_chunks(
        self,
        document_id: str,
        page: int,
        page_size: int,
        search: str | None,
    ) -> tuple[list[object], int]:
        from app.models.domain import Chunk  # noqa: PLC0415

        params: dict[str, str] = {
            "document_id": f"eq.{document_id}",
            "order": "chunk_index.asc",
            "limit": str(page_size),
            "offset": str((page - 1) * page_size),
        }
        if search:
            # ``ilike`` di PostgREST bersifat case-insensitive, jadi tidak
            # perlu menurunkan ke huruf kecil seperti di SQLite.
            params["content"] = f"ilike.%{search.strip()}%"

        # Data dan total diambil dalam satu request. Dua request berarti
        # angka ``total`` bisa tidak cocok dengan isi halaman kalau ada
        # dokumen lain yang diunggah di antara keduanya.
        rows, total = self._request(
            "GET", "chunks", params=params, want_range_count=True
        )
        chunks = [
            Chunk(
                id=row["id"],
                document_id=row["document_id"],
                chunk_index=int(row["chunk_index"]),
                content=row["content"],
                page_number=row.get("page_number"),
                token_count=row.get("token_count"),
                char_start=int(row.get("char_start") or 0),
                char_end=int(row.get("char_end") or 0),
            )
            for row in rows or []
        ]
        return chunks, total

    def delete_chunks(self, document_id: str) -> None:
        self._request("DELETE", "chunks", params={"document_id": f"eq.{document_id}"})

    def all_chunks(self) -> list[object]:
        """Semua chunk dengan nama dokumennya, untuk rebuild indeks saat startup.

        Sengaja tidak dipaginasi: rebuild indeks butuh SELURUH corpus dalam
        satu-pass, bukan satu halaman. Aman untuk skala portofolio. Kalau
        corpus tumbuh sampai ratusan ribu baris, ganti ke stream/cursor,
        memuat semuanya ke memori akan jadi masalah sebelum jadi lambat.
        """
        from app.models.domain import Chunk  # noqa: PLC0415

        rows = self._request(
            "GET",
            "chunks",
            params={
                "select": (
                    "id,document_id,chunk_index,content,page_number,"
                    "token_count,char_start,char_end,documents(filename)"
                ),
                "order": "document_id,chunk_index",
            },
        )
        chunks: list[object] = []
        for row in rows or []:
            parent = row.get("documents") or {}
            filename = parent.get("filename") if isinstance(parent, dict) else None
            chunks.append(
                Chunk(
                    id=row["id"],
                    document_id=row["document_id"],
                    chunk_index=int(row["chunk_index"]),
                    content=row["content"],
                    page_number=row.get("page_number"),
                    token_count=row.get("token_count"),
                    char_start=int(row.get("char_start") or 0),
                    char_end=int(row.get("char_end") or 0),
                    # Fallback dipakai kalau dokumen induknya sudah hilang, agar
                    # sitasi tetap punya sumber yang bisa ditampilkan.
                    document_name=filename or "dokumen",
                )
            )
        return chunks

    # ------------------------------------------------------------- sessions
    def upsert_session(self, session: ChatSession) -> None:
        self._request(
            "POST",
            "sessions",
            params={"on_conflict": "id"},
            json_body={
                "id": session.id,
                "title": session.title,
                "created_at": session.created_at,
                "last_active_at": session.last_active_at,
                "message_count": session.message_count,
                "document_id": session.document_id,
                "document_ids": session.document_ids,
            },
        )

    def get_session(self, session_id: str) -> ChatSession | None:
        rows = self._request("GET", "sessions", params={"id": f"eq.{session_id}", "limit": "1"})
        return _to_session(rows[0]) if rows else None

    def list_sessions(self) -> list[ChatSession]:
        rows = self._request("GET", "sessions", params={"order": "last_active_at.desc"})
        return [_to_session(row) for row in rows or []]

    def rename_session(self, session_id: str, title: str) -> bool:
        # Sengaja tidak menyentuh last_active_at, sama seperti SQLite.
        self._request(
            "PATCH",
            "sessions",
            params={"id": f"eq.{session_id}"},
            json_body={"title": title},
        )
        return self.get_session(session_id) is not None

    def delete_session(self, session_id: str) -> bool:
        self._request("DELETE", "sessions", params={"id": f"eq.{session_id}"})
        return True

    def delete_all_sessions(self) -> int:
        before = self.list_sessions()
        self._request("DELETE", "sessions", params={"id": "not.is.null"})
        return len(before)

    # ------------------------------------------------------------- settings
    def get_settings(self) -> RetrievalSettings:
        rows = self._request("GET", "app_settings", params={"select": "key,value"})
        stored = {row["key"]: row["value"] for row in rows or []}
        return RetrievalSettings(
            top_k=int(stored.get("top_k", 5)),
            similarity_threshold=float(stored.get("similarity_threshold", 0.35)),
        )

    def update_settings(self, patch: dict[str, object]) -> RetrievalSettings:
        now = utc_now()
        for key, value in patch.items():
            if value is None:
                continue
            self._request(
                "POST",
                "app_settings",
                params={"on_conflict": "key"},
                json_body={"key": key, "value": str(value), "updated_at": now},
            )
        return self.get_settings()

    # ----------------------------------------------------------------- logs
    def add_log(self, log: QueryLog) -> None:
        self._request(
            "POST",
            "query_logs",
            json_body={
                "id": log.id,
                "session_id": log.session_id,
                "question": log.question,
                "response_time_ms": log.response_time_ms,
                "sources_count": log.sources_count,
                "created_at": log.created_at,
                "from_cache": log.from_cache,
                "trace_id": log.trace_id,
            },
        )

    def list_logs(self, page: int, page_size: int) -> tuple[list[QueryLog], int]:
        rows, total = self._request(
            "GET",
            "query_logs",
            params={
                "order": "created_at.desc",
                "limit": str(page_size),
                "offset": str((page - 1) * page_size),
            },
            want_range_count=True,
        )
        logs = [_to_log(row) for row in rows or []]
        return logs, total

    def latency_by_day(self, days: int) -> list[dict[str, object]]:
        from app.repositories.sqlite_repo import _latency_point  # noqa: PLC0415

        rows = self._request("GET", "query_logs", params={"select": "created_at,response_time_ms"})
        buckets: dict[str, list[int]] = {}
        for row in rows or []:
            buckets.setdefault(str(row["created_at"])[:10], []).append(int(row["response_time_ms"]))
        return [_latency_point(day, values) for day, values in list(buckets.items())[-days:]]

    def tokens_by_day(self, days: int) -> list[dict[str, object]]:
        rows = self._request(
            "GET", "query_logs", params={"select": "created_at,question,sources_count"}
        )
        buckets: dict[str, dict[str, int]] = {}
        for row in rows or []:
            day = str(row["created_at"])[:10]
            bucket = buckets.setdefault(day, {"input_tokens": 0, "output_tokens": 0})
            bucket["input_tokens"] += max(1, len(str(row["question"])) // 4) + 2000
            bucket["output_tokens"] += int(row["sources_count"]) * 480 + 180
        return [{"date": day, **values} for day, values in list(buckets.items())[-days:]]

    # ----------------------------------------------------------------- eval
    def latest_eval(self) -> dict[str, object] | None:
        rows = self._request("GET", "eval_runs", params={"order": "run_at.desc", "limit": "1"})
        if not rows:
            return None
        row = rows[0]
        return {
            "id": row["id"],
            "precision": row.get("precision"),
            "faithfulness": row.get("faithfulness"),
            "answer_relevance": row.get("answer_relevance"),
            "run_at": row["run_at"],
        }

    def add_eval_run(self, run: dict[str, object]) -> None:
        self._request(
            "POST",
            "eval_runs",
            json_body={
                "id": str(run.get("id") or new_id("eval")),
                "precision": run.get("precision"),
                "faithfulness": run.get("faithfulness"),
                "answer_relevance": run.get("answer_relevance"),
                "run_at": str(run.get("run_at") or utc_now()),
            },
        )

    def ping(self) -> bool:
        try:
            self._request("GET", "documents", params={"limit": "1"})
            return True
        except Exception:  # noqa: BLE001
            return False


def _to_document(row: dict[str, Any]) -> Document:
    return Document(
        id=row["id"],
        filename=row["filename"],
        size_bytes=int(row["size_bytes"]),
        status=DocumentStatus(row["status"]),
        uploaded_at=row["uploaded_at"],
        page_count=row.get("page_count"),
        chunk_count=int(row.get("chunk_count") or 0),
        error_message=row.get("error_message"),
    )


def _to_session(row: dict[str, Any]) -> ChatSession:
    mentah_ids = row.get("document_ids")
    document_ids: list[str] | None = None
    if isinstance(mentah_ids, list):
        document_ids = [str(item) for item in mentah_ids if isinstance(item, str)] or None

    return ChatSession(
        id=row["id"],
        title=row["title"],
        created_at=row["created_at"],
        last_active_at=row["last_active_at"],
        message_count=int(row.get("message_count") or 0),
        # `document_id` ikut dibaca, bukan hanya ditulis. Versi sebelumnya
        # hanya mengirimnya saat upsert tapi tidak pernah membacanya kembali,
        # jadi scope dokumen sesi hilang setiap kali sesi dimuat ulang, dan
        # pertanyaan lanjutan diam-diam mencari di seluruh dokumen. Kolomnya
        # memakai `.get` karena database yang belum dimigrasi tidak punya
        # kolom ini, dan KeyError di sini akan menjatuhkan seluruh daftar sesi.
        document_id=row.get("document_id"),
        document_ids=document_ids,
    )


def _to_log(row: dict[str, Any]) -> QueryLog:
    return QueryLog(
        id=row["id"],
        session_id=row.get("session_id"),
        question=row["question"],
        response_time_ms=int(row["response_time_ms"]),
        sources_count=int(row["sources_count"]),
        created_at=row["created_at"],
        from_cache=bool(row.get("from_cache")),
        trace_id=row.get("trace_id"),
    )
