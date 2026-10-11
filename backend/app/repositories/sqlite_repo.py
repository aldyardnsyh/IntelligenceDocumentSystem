"""Repository metadata.

PRD 8.5 menetapkan PostgreSQL sebagai tempat metadata. Tapi Supabase free-tier
bisa di-pause setelah 1 minggu idle, dan portofolio harus tetap bisa jalan
tanpa akun cloud apa pun. Karena itu ada dua implementasi:

- ``SupabaseRepository`` kalau ``SUPABASE_URL`` dan ``SUPABASE_SERVICE_KEY`` ada.
- ``SqliteRepository`` sebagai default, pakai berkas lokal.

Keduanya memenuhi protokol ``MetadataRepository`` yang sama, jadi service tidak
perlu tahu yang mana yang aktif. Perbedaan perilaku dilaporkan lewat
``/api/v1/health``.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
import uuid
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from app.models.domain import (
    ChatSession,
    Document,
    DocumentStatus,
    QueryLog,
    RetrievalSettings,
)

if TYPE_CHECKING:
    from app.core.config import Settings

logger = logging.getLogger(__name__)


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


@runtime_checkable
class MetadataRepository(Protocol):
    """Penyimpanan metadata dokumen, sesi, pengaturan, dan log."""

    name: str

    # documents
    def add_document(self, document: Document) -> None: ...
    def get_document(self, document_id: str) -> Document | None: ...
    def list_documents(self) -> list[Document]: ...
    def update_document(self, document_id: str, **changes: object) -> None: ...
    def delete_document(self, document_id: str) -> None: ...

    # chunks
    def add_chunks(self, chunks: Iterable[object], document_id: str) -> None: ...
    def get_chunks(
        self,
        document_id: str,
        page: int,
        page_size: int,
        search: str | None,
    ) -> tuple[list[object], int]: ...
    def delete_chunks(self, document_id: str) -> None: ...
    def all_chunks(self) -> list[object]:
        """Semua chunk yang tersimpan, dengan nama dokumen.

        Dipakai untuk membangun ulang indeks retrieval saat startup. Tanpa ini,
        indeks kata hanya terisi oleh dokumen yang diunggah selama proses
        berjalan, dan setelah restart seluruh pencarian gagal.
        """
        ...

    # sessions
    def upsert_session(self, session: ChatSession) -> None: ...
    def get_session(self, session_id: str) -> ChatSession | None: ...
    def list_sessions(self) -> list[ChatSession]: ...
    def rename_session(self, session_id: str, title: str) -> bool: ...
    def delete_session(self, session_id: str) -> bool: ...
    def delete_all_sessions(self) -> int: ...

    # settings
    def get_settings(self) -> RetrievalSettings: ...
    def update_settings(self, patch: dict[str, object]) -> RetrievalSettings: ...

    # logs
    def add_log(self, log: QueryLog) -> None: ...
    def list_logs(self, page: int, page_size: int) -> tuple[list[QueryLog], int]: ...
    def latency_by_day(self, days: int) -> list[dict[str, object]]: ...
    def tokens_by_day(self, days: int) -> list[dict[str, object]]: ...

    # eval
    def latest_eval(self) -> dict[str, object] | None: ...
    def add_eval_run(self, run: dict[str, object]) -> None: ...

    def ping(self) -> bool: ...


#: Batas baris yang dipindai saat menghitung agregasi harian. Dipakai di
#: ``LIMIT`` SQL supaya permintaan dashboard tidak membaca seluruh tabel yang
#: terus bertambah.
_ANALYTICS_SCAN_LIMIT = 20_000

_SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    id TEXT PRIMARY KEY,
    filename TEXT NOT NULL,
    size_bytes INTEGER NOT NULL,
    status TEXT NOT NULL,
    uploaded_at TEXT NOT NULL,
    page_count INTEGER,
    chunk_count INTEGER NOT NULL DEFAULT 0,
    error_message TEXT
);
CREATE TABLE IF NOT EXISTS chunks (
    id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL,
    chunk_index INTEGER NOT NULL,
    content TEXT NOT NULL,
    page_number INTEGER,
    token_count INTEGER,
    char_start INTEGER NOT NULL DEFAULT 0,
    char_end INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_chunks_document ON chunks(document_id);
CREATE INDEX IF NOT EXISTS idx_chunks_index ON chunks(document_id, chunk_index);
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    document_id TEXT,
    created_at TEXT NOT NULL,
    last_active_at TEXT NOT NULL,
    message_count INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS query_logs (
    id TEXT PRIMARY KEY,
    session_id TEXT,
    question TEXT NOT NULL,
    response_time_ms INTEGER NOT NULL,
    sources_count INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    from_cache INTEGER NOT NULL DEFAULT 0,
    trace_id TEXT
);
CREATE INDEX IF NOT EXISTS idx_logs_created ON query_logs(created_at);
CREATE TABLE IF NOT EXISTS eval_runs (
    id TEXT PRIMARY KEY,
    precision REAL,
    faithfulness REAL,
    answer_relevance REAL,
    run_at TEXT NOT NULL
);
"""


class SqliteRepository:
    """Metadata di SQLite lokal. Default saat Supabase tidak dikonfigurasi."""

    name = "sqlite"

    def __init__(self, path: str, defaults: Settings | None = None) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        # Settings dipakai untuk nilai default saat baris belum ada. Diterima
        # sebagai argumen, bukan dibaca dari env global: kalau dibaca dari
        # env, aplikasi yang dibangun dengan Settings khusus (test, script,
        # instance kedua) diam-diam memakai default instance lain.
        self._defaults = defaults
        with self._connect() as connection:
            connection.executescript(_SCHEMA)
            self._migrate(connection)

    @staticmethod
    def _migrate(connection: sqlite3.Connection) -> None:
        """Tambah kolom baru pada database yang sudah ada.

        `CREATE TABLE IF NOT EXISTS` tidak pernah menyentuh tabel yang sudah
        dibuat, jadi kolom baru hanya ada di database baru. Tanpa migrasi
        ini, `INSERT` yang menyebut kolom `document_id` gagal pada database
        pengguna yang sudah berjalan, bukan error yang hilang sendiri.
        """
        columns = {row["name"] for row in connection.execute("PRAGMA table_info(sessions)")}
        if "document_id" not in columns:
            connection.execute("ALTER TABLE sessions ADD COLUMN document_id TEXT")

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._path, check_same_thread=False)
        connection.row_factory = sqlite3.Row
        return connection

    # ------------------------------------------------------------ documents
    def add_document(self, document: Document) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO documents "
                "(id, filename, size_bytes, status, uploaded_at, "
                "page_count, chunk_count, error_message) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    document.id,
                    document.filename,
                    document.size_bytes,
                    document.status.value,
                    document.uploaded_at,
                    document.page_count,
                    document.chunk_count,
                    document.error_message,
                ),
            )

    def get_document(self, document_id: str) -> Document | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM documents WHERE id = ?", (document_id,)
            ).fetchone()
        return _row_to_document(row) if row else None

    def list_documents(self) -> list[Document]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM documents ORDER BY uploaded_at DESC"
            ).fetchall()
        return [_row_to_document(row) for row in rows]

    def update_document(self, document_id: str, **changes: object) -> None:
        allowed = {"status", "chunk_count", "page_count", "error_message", "filename"}
        fields = {key: value for key, value in changes.items() if key in allowed}
        if not fields:
            return
        if isinstance(fields.get("status"), DocumentStatus):
            fields["status"] = fields["status"].value
        assignments = ", ".join(f"{key} = ?" for key in fields)
        with self._lock, self._connect() as connection:
            connection.execute(
                f"UPDATE documents SET {assignments} WHERE id = ?",
                (*fields.values(), document_id),
            )

    def delete_document(self, document_id: str) -> None:
        with self._lock, self._connect() as connection:
            connection.execute("DELETE FROM documents WHERE id = ?", (document_id,))
            connection.execute("DELETE FROM chunks WHERE document_id = ?", (document_id,))

    # --------------------------------------------------------------- chunks
    def add_chunks(self, chunks: Iterable[object], document_id: str) -> None:
        rows = [
            (
                chunk.id,
                document_id,
                chunk.chunk_index,
                chunk.content,
                chunk.page_number,
                chunk.token_count,
                getattr(chunk, "char_start", 0),
                getattr(chunk, "char_end", 0),
            )
            for chunk in chunks
        ]
        if not rows:
            return
        with self._lock, self._connect() as connection:
            connection.executemany(
                "INSERT OR REPLACE INTO chunks "
                "(id, document_id, chunk_index, content, page_number, "
                "token_count, char_start, char_end) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                rows,
            )

    def get_chunks(
        self,
        document_id: str,
        page: int,
        page_size: int,
        search: str | None,
    ) -> tuple[list[object], int]:
        with self._connect() as connection:
            if search:
                pattern = f"%{search.strip().lower()}%"
                total = connection.execute(
                    "SELECT COUNT(*) FROM chunks WHERE document_id = ? AND LOWER(content) LIKE ?",
                    (document_id, pattern),
                ).fetchone()[0]
                rows = connection.execute(
                    "SELECT * FROM chunks WHERE document_id = ? AND LOWER(content) LIKE ? "
                    "ORDER BY chunk_index ASC LIMIT ? OFFSET ?",
                    (document_id, pattern, page_size, (page - 1) * page_size),
                ).fetchall()
            else:
                total = connection.execute(
                    "SELECT COUNT(*) FROM chunks WHERE document_id = ?", (document_id,)
                ).fetchone()[0]
                rows = connection.execute(
                    "SELECT * FROM chunks WHERE document_id = ? "
                    "ORDER BY chunk_index ASC LIMIT ? OFFSET ?",
                    (document_id, page_size, (page - 1) * page_size),
                ).fetchall()
        return [_row_to_chunk(row) for row in rows], int(total)

    def delete_chunks(self, document_id: str) -> None:
        with self._lock, self._connect() as connection:
            connection.execute("DELETE FROM chunks WHERE document_id = ?", (document_id,))

    def all_chunks(self) -> list[object]:
        """Semua chunk, digabung dengan nama dokumennya.

        Dipakai untuk membangun ulang indeks retrieval saat startup. Nama
        dokumen ikut diambil karena tabel ``chunks`` tidak menyimpannya, dan
        sitasi butuh nama itu untuk ditampilkan.
        """
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT c.*, d.filename AS document_name "
                "FROM chunks c LEFT JOIN documents d ON d.id = c.document_id "
                "ORDER BY c.document_id, c.chunk_index"
            ).fetchall()
        return [_row_to_chunk(row) for row in rows]

    # ------------------------------------------------------------- sessions
    def upsert_session(self, session: ChatSession) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO sessions "
                "(id, title, created_at, last_active_at, message_count, document_id) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    session.id,
                    session.title,
                    session.created_at,
                    session.last_active_at,
                    session.message_count,
                    session.document_id,
                ),
            )

    def get_session(self, session_id: str) -> ChatSession | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM sessions WHERE id = ?", (session_id,)
            ).fetchone()
        return _row_to_session(row) if row else None

    def list_sessions(self) -> list[ChatSession]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM sessions ORDER BY last_active_at DESC"
            ).fetchall()
        return [_row_to_session(row) for row in rows]

    def rename_session(self, session_id: str, title: str) -> bool:
        """Ubah judul tanpa menyentuh ``last_active_at``.

        Mengganti nama bukan aktivitas percakapan, jadi waktu aktivitas tidak
        ikut berubah. Kalau ikut berubah, sesi yang cuma dirapikan akan naik
        ke atas daftar dan urutannya berubah.
        """
        with self._lock, self._connect() as connection:
            cursor = connection.execute(
                "UPDATE sessions SET title = ? WHERE id = ?", (title, session_id)
            )
        return cursor.rowcount > 0

    def delete_session(self, session_id: str) -> bool:
        with self._lock, self._connect() as connection:
            cursor = connection.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
        return cursor.rowcount > 0

    def delete_all_sessions(self) -> int:
        with self._lock, self._connect() as connection:
            cursor = connection.execute("DELETE FROM sessions")
        return cursor.rowcount

    # ------------------------------------------------------------- settings
    def get_settings(self) -> RetrievalSettings:
        """Baca parameter retrieval yang aktif.

        Default diambil dari Settings instance ini kalau ada; env global hanya
        upaya terakhir. Membaca env langsung membuat aplikasi yang dibangun
        dengan Settings khusus (test, script, instance kedua) diam-diam
        memakai default instance lain.
        """
        with self._connect() as connection:
            rows = connection.execute("SELECT key, value FROM settings").fetchall()
        stored = {row["key"]: row["value"] for row in rows}
        if self._defaults is not None:
            defaults = self._defaults
        else:
            from app.core.config import get_settings as load_settings

            defaults = load_settings()
        return RetrievalSettings(
            top_k=int(stored.get("top_k", defaults.default_top_k)),
            similarity_threshold=float(
                stored.get(
                    "similarity_threshold", defaults.default_similarity_threshold
                )
            ),
        )

    def update_settings(self, patch: dict[str, object]) -> RetrievalSettings:
        now = utc_now()
        with self._lock, self._connect() as connection:
            for key, value in patch.items():
                if value is None:
                    continue
                connection.execute(
                    "INSERT OR REPLACE INTO settings (key, value, updated_at) VALUES (?, ?, ?)",
                    (key, json.dumps(value), now),
                )
        return self.get_settings()

    # ----------------------------------------------------------------- logs
    def add_log(self, log: QueryLog) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO query_logs "
                "(id, session_id, question, response_time_ms, "
                "sources_count, created_at, from_cache, trace_id) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    log.id,
                    log.session_id,
                    log.question,
                    log.response_time_ms,
                    log.sources_count,
                    log.created_at,
                    1 if log.from_cache else 0,
                    log.trace_id,
                ),
            )

    def list_logs(self, page: int, page_size: int) -> tuple[list[QueryLog], int]:
        with self._connect() as connection:
            total = connection.execute("SELECT COUNT(*) FROM query_logs").fetchone()[0]
            rows = connection.execute(
                "SELECT * FROM query_logs ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (page_size, (page - 1) * page_size),
            ).fetchall()
        return [_row_to_log(row) for row in rows], int(total)

    def latency_by_day(self, days: int) -> list[dict[str, object]]:
        """Agregasi latensi per hari dari log yang benar-benar tercatat.

        Baris yang dipindai dibatasi dengan ``LIMIT`` di SQL, bukan dipotong
        di Python. Versi lama memuat seluruh tabel ``query_logs`` ke memori
        setiap kali dashboard dibuka, jadi biaya permintaan tumbuh seiring
        pemakaian padahal yang dibutuhkan hanya ``days`` terakhir.
        """
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT SUBSTR(created_at, 1, 10) AS day, response_time_ms "
                "FROM query_logs ORDER BY day DESC LIMIT ?",
                (_ANALYTICS_SCAN_LIMIT,),
            ).fetchall()

        buckets: dict[str, list[int]] = {}
        for row in rows:
            buckets.setdefault(row["day"], []).append(int(row["response_time_ms"]))

        # Diurutkan ulang sebelum dipotong: query diambil DESC supaya yang
        # terbaru masuk lebih dulu, dan dashboard ingin urutan kronologis.
        return [_latency_point(day, values) for day, values in sorted(buckets.items())[-days:]]

    def tokens_by_day(self, days: int) -> list[dict[str, object]]:
        """Token usage yang dihitung dari log.

        Frontend menampilkan angka ini apa adanya, jadi backend harus
        mengatakannya dengan jujur: ini estimasi dari panjang pertanyaan dan
        jumlah sumber, bukan jumlah token yang dilaporkan penyedia. Angka tetap
        tidak membuat estimasi berubah menjadi pengukuran.

        Karena itu respons analitik menyertakan flag ``estimated`` supaya
        frontend bisa menandainya, bukan memamerkannya sebagai fakta.
        """
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT SUBSTR(created_at, 1, 10) AS day, question, sources_count "
                "FROM query_logs ORDER BY day DESC LIMIT ?",
                (_ANALYTICS_SCAN_LIMIT,),
            ).fetchall()

        buckets: dict[str, dict[str, int]] = {}
        for row in rows:
            day = row["day"]
            bucket = buckets.setdefault(day, {"input_tokens": 0, "output_tokens": 0})
            question_tokens = max(1, len(str(row["question"])) // 4)
            # contexts: pertanyaan + cuplikan sumber. Dipakai angka tetap
            # supaya estimasi bisa direproduksi.
            bucket["input_tokens"] += question_tokens + 2000
            bucket["output_tokens"] += int(row["sources_count"]) * 480 + 180

        return [
            {"date": day, **values, "estimated": True}
            for day, values in sorted(buckets.items())[-days:]
        ]

    # ----------------------------------------------------------------- eval
    def latest_eval(self) -> dict[str, object] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM eval_runs ORDER BY run_at DESC LIMIT 1"
            ).fetchone()
        if not row:
            return None
        return {
            "id": row["id"],
            "precision": row["precision"],
            "faithfulness": row["faithfulness"],
            "answer_relevance": row["answer_relevance"],
            "run_at": row["run_at"],
        }

    def add_eval_run(self, run: dict[str, object]) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO eval_runs "
                "(id, precision, faithfulness, answer_relevance, run_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    str(run.get("id") or new_id("eval")),
                    run.get("precision"),
                    run.get("faithfulness"),
                    run.get("answer_relevance"),
                    str(run.get("run_at") or utc_now()),
                ),
            )

    def ping(self) -> bool:
        try:
            with self._connect() as connection:
                connection.execute("SELECT 1")
            return True
        except sqlite3.Error:
            return False


def _latency_point(day: str, values: list[int]) -> dict[str, object]:
    """Rata-rata dan persentil 95 dari daftar durasi.

    Persentil dihitung dengan indeks terdekat, bukan interpolasi, supaya
    angkanya selalu salah satu durasi yang benar-benar terjadi.
    """
    ordered = sorted(values)
    average = sum(ordered) / len(ordered)
    index = min(len(ordered) - 1, int(len(ordered) * 0.95))
    return {"date": day, "avg_ms": round(average), "p95_ms": ordered[index]}


def _row_to_document(row: sqlite3.Row) -> Document:
    return Document(
        id=row["id"],
        filename=row["filename"],
        size_bytes=int(row["size_bytes"]),
        status=DocumentStatus(row["status"]),
        uploaded_at=row["uploaded_at"],
        page_count=row["page_count"],
        chunk_count=int(row["chunk_count"] or 0),
        error_message=row["error_message"],
    )


def _row_to_chunk(row: sqlite3.Row) -> object:
    """Baris chunk menjadi objek Chunk.

    Kalau baris hasil join (``all_chunks``), kolom ``document_name`` ikut
    dibaca. Baris dari ``get_chunks`` tidak punya kolom itu, jadi
    ``row.keys`` dipakai untuk mendeteksi keberadaan kolom alih-alih
    menglezatkan KeyError.
    """
    from app.models.domain import Chunk  # noqa: PLC0415

    # `row.keys()` dipakai, bukan `in row`: `sqlite3.Row` mengimplementasikan
    # `keys()` dan `__getitem__`, tetapi `__contains__`-nya menguji nilai,
    # bukan nama kolom, jadi `in row` akan selalu salah untuk kolom string.
    columns = set(row.keys())

    return Chunk(
        id=row["id"],
        document_id=row["document_id"],
        chunk_index=int(row["chunk_index"]),
        content=row["content"],
        page_number=row["page_number"],
        token_count=row["token_count"],
        char_start=int(row["char_start"] or 0),
        char_end=int(row["char_end"] or 0),
        # LEFT JOIN bisa menghasilkan NULL kalau dokumen induknya sudah
        # dihapus. Nama cadangan dipakai supaya sitasi tetap punya sumber yang
        # bisa ditampilkan, meski label aslinya tidak ada lagi.
        document_name=(
            (row["document_name"] or "dokumen") if "document_name" in columns else None
        ),
    )


def _row_to_session(row: sqlite3.Row) -> ChatSession:
    keys = row.keys()
    return ChatSession(
        id=row["id"],
        title=row["title"],
        created_at=row["created_at"],
        last_active_at=row["last_active_at"],
        message_count=int(row["message_count"] or 0),
        # Kolom hanya ada setelah migrasi; baris lama dibaca sebagai sesi global.
        document_id=row["document_id"] if "document_id" in keys else None,
    )


def _row_to_log(row: sqlite3.Row) -> QueryLog:
    return QueryLog(
        id=row["id"],
        session_id=row["session_id"],
        question=row["question"],
        response_time_ms=int(row["response_time_ms"]),
        sources_count=int(row["sources_count"]),
        created_at=row["created_at"],
        from_cache=bool(row["from_cache"]),
        trace_id=row["trace_id"],
    )
