"""Konfigurasi aplikasi.

Semua nilai sensitif dibaca dari environment variable. Tidak ada API key,
password, atau passcode yang tertulis di source, jadi tidak ada rahasia yang
ikut ter-commit.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated, Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

LlmProviderName = Literal["groq", "ollama", "sglang", "mock"]


class Settings(BaseSettings):
    """Konfigurasi runtime.

    Sumber nilai: environment variable, lalu berkas ``.env``. Tidak ada nilai
    rahasia yang punya default di sini, kecuali yang memang tidak rahasia
    (nama model, ukuran chunk, port).
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ------------------------------------------------------------------ app
    app_name: str = "Intelligent Document Assistant API"
    version: str = "1.0.0"
    debug: bool = False
    # Origin frontend yang diizinkan. Dipakai CORS.
    #
    # ``NoDecode`` wajib ada di sini. Tanpa itu, pydantic-settings mencoba
    # ``json.loads`` pada nilai env **sebelum** validator berjalan, jadi
    # ``CORS_ORIGINS=http://localhost:3000`` gagal dengan JSONDecodeError.
    # Nilai env memang ditulis sebagai daftar dipisah koma, bukan JSON.
    #
    # JANGAN isi dengan ``*``. Aplikasi ini memakai cookie sesi, dan
    # ``allow_credentials=True`` membuat Starlette memantulkan origin
    # pemanggil apa adanya begitu request membawa cookie. Artinya situs mana
    # pun bisa membaca respons API ini memakai sesi pengguna yang sedang
    # login. Validator di bawah menolaknya, bukan hanya memperingatkan.
    cors_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:3000"]
    )

    # ------------------------------------------------------------- security
    """Hash passcode access gate.

    Bandingkan dengan hash, bukan plaintext, supaya bocornya isi environment
    tidak langsung berarti bypass. Verifikasi happened di
    ``app.core.security``.
    """
    access_passcode_sha256: str | None = None
    """Sesi access gate berlaku berapa detik. Default 24 jam."""
    session_ttl_seconds: int = 60 * 60 * 24
    """Rate limit verifikasi passcode: jumlah percobaan per jendela waktu."""
    auth_max_attempts: int = 5
    auth_window_seconds: int = 5 * 60
    """Percayai ``X-Forwarded-For`` untuk key rate limit.

    Hanya nyalakan kalau API benar-benar hanya dijangkau lewat reverse proxy
    tepercaya (Caddy di docker compose). Tanpa proxy, `request.client.host`
    sudah merupakan IP asli dan mengaktifkan ini membuat klien bisa menyusun
    ulang bucket rate limit sesuka hatinya lewat header palsu.
    """
    trust_proxy_headers: bool = False

    """Tampilkan dokumentasi API interaktif di ``/docs`` dan ``/redoc``.

    Dimatikan secara default karena ini aplikasi yang menampilkan dokumen
    pribadi, bukan API publik. Skema OpenAPI di ``/openapi.json`` memuat
    seluruh bentuk request dan response, termasuk nama field internal, dan
    halaman ``/docs`` membiarkan siapa pun mencoba endpoint tanpa perlu
    menulis kode. Itu permukaan yang tidak perlu terbuka di produksi.

    Nyalakan (``API_DOCS_ENABLED=1``) kalau aplikasinya memang dipakai
    sebagai demo portofolio dan halaman /about menautkan ke sana. Saat
    dimatikan, ``/openapi.json`` ikut mati: membiarkannya hidup akan
    membocorkan hal yang sama lewat jalur lain.
    """
    api_docs_enabled: bool = False

    # ------------------------------------------------------------------- llm
    """Provider aktif untuk generation. Ganti ke ``ollama`` untuk fully local."""
    llm_provider: LlmProviderName = "mock"
    """Rantai fallback. Kalau provider pertama kena 429, dicoba yang berikutnya.

    Misal ``groq,ollama``: pakai Groq, kalau limit kena pindah ke Ollama.
    ``NoDecode`` supaya env dibaca sebagai daftar dipisah koma, bukan JSON.
    """
    llm_fallback_chain: Annotated[list[str], NoDecode] = Field(default_factory=list)
    llm_model: str = "openai/gpt-oss-20b"
    llm_temperature: float = 0.1
    llm_max_tokens: int = 800
    llm_timeout_seconds: float = 30.0
    """Batas keras agar satu request yang macet tidak membekukan workers."""
    llm_max_retries: int = 3

    groq_api_key: str | None = None
    groq_base_url: str = "https://api.groq.com/openai/v1"

    ollama_base_url: str = "http://localhost:11434/v1"
    ollama_model: str = "qwen2.5:3b"

    sglang_base_url: str = "http://localhost:30000/v1"
    sglang_model: str = "qwen2.5-3b-instruct"

    # ------------------------------------------------------------- embedding
    """Model embedding lokal (nol biaya, data tidak keluar).

    Default memakai model multilingual karena dokumen dan pertanyaan dalam
    bahasa Indonesia. Model Inggris-first seperti all-MiniLM-L6-v2 menghasilkan
    vektor yang jauh lebih buruk untuk Bahasa Indonesia.
    """
    embedding_model: str = "intfloat/multilingual-e5-small"
    embedding_dimension: int = 384
    embedding_batch_size: int = 16
    """Diaktifkan hanya kalau env ``USE_LOCAL_EMBEDDING=0``; test memakai stub."""
    use_local_embedding: bool = True

    # ------------------------------------------------------------- chunking
    chunk_size: int = 500
    chunk_overlap: int = 50

    # -------------------------------------------------------------- retrieval
    default_top_k: int = 5
    min_top_k: int = 3
    max_top_k: int = 10
    # Rentang di sini adalah sumber kebenaran; slider di frontend harus
    # mengikuti angka yang sama.
    #
    # Angka ini diukur, bukan ditebak. Dengan `multilingual-e5-small`, pertanyaan
    # yang benar-benar relevan skornya 0.84-0.91, sedangkan yang tidak relevan
    # masih 0.72-0.81, model embedding memang selalu memberi skor cukup tinggi
    # pada teks bahasa Indonesia. Ambang lama 0.5 dibuat untuk stub hashing dan
    # berbahaya di sini: pertanyaan tentang sepak bola lolos, lalu LLM menjawab
    # berdasarkan chunk yang salah (lebih buruk daripada "tidak ditemukan",
    # karena sekarang jawabannya terlihat bersumber).
    default_similarity_threshold: float = 0.82
    min_similarity_threshold: float = 0.75
    max_similarity_threshold: float = 0.92
    """Berapa pesan terakhir yang ikut sebagai konteks."""
    history_message_count: int = 6
    """Cache query: TTL dan key."""
    cache_ttl_seconds: int = 30 * 60
    """Rate limit query per sesi, untuk melindungi kuota free tier."""
    query_max_per_session: int = 20
    query_window_seconds: int = 60

    # ------------------------------------------------------------- documents
    max_file_size_bytes: int = 10 * 1024 * 1024
    accepted_extensions: list[str] = Field(
        default_factory=lambda: [".pdf", ".txt", ".md", ".markdown"]
    )
    """Berkas golden dataset untuk evaluasi retrieval dari UI.

    Dipakai endpoint ``POST /analytics/evaluate``. Path relatif dihitung dari
    direktori kerja proses (biasanya ``backend/``).
    """
    evaluation_dataset_path: str = "evaluation/dataset.json"

    # ----------------------------------------------------------------- redis
    redis_url: str | None = None
    upstash_redis_url: str | None = None
    upstash_redis_token: str | None = None
    session_memory_ttl_seconds: int = 60 * 60

    # --------------------------------------------------------------- storage
    chroma_persist_dir: str = "./data/chroma"
    sqlite_fallback_path: str = "./data/metadata.db"
    """Berkas asli yang disimpan untuk pratinjau (PDF).

    Dipisah dari metadata dan vector store karena isinya biner dan besar.
    Yang disimpan hanya jenis berkas yang tidak bisa ditampilkan dari
    chunk (lihat ``STORED_SUFFIXES`` di ``app/services/storage.py``).
    """
    uploads_dir: str = "./data/uploads"

    # -------------------------------------------------------------- supabase
    supabase_url: str | None = None
    supabase_service_key: str | None = None

    # ------------------------------------------------------------- langfuse
    langfuse_public_key: str | None = None
    langfuse_secret_key: str | None = None
    langfuse_host: str = "https://cloud.langfuse.com"
    tracing_enabled: bool = False

    # ----------------------------------------------------------------- cors
    @field_validator("llm_fallback_chain", mode="before")
    @classmethod
    def _split_fallback(cls, value: object) -> object:
        """Terima ``"groq,ollama"`` dari env dan pecah jadi list."""
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @field_validator("cors_origins")
    @classmethod
    def _reject_wildcard_origin(cls, value: list[str]) -> list[str]:
        """Tolak ``*`` di CORS.

        Ini bukan peringatan, tapi penolakan. Aplikasi ini memakai cookie
        sesi, dan Starlette dengan ``allow_credentials=True`` memantulkan
        origin pemanggil apa adanya begitu request membawa cookie. Dengan
        ``*``, situs mana pun bisa membaca respons API ini memakai sesi
        pengguna yang sedang login.

        Nilai ``*`` mudah ditulis karena "cara cepat supaya jalan", dan
        efeknya tidak terlihat sampai ada yang menyalahgunakannya. Lebih
        baik gagal saat start dengan pesan yang menjelaskan daripada jalan
        dengan lubang yang tidak kelihatan.
        """
        if "*" in value:
            raise ValueError(
                "CORS_ORIGINS tidak boleh berisi '*'. Aplikasi ini memakai cookie "
                "sesi, jadi origin harus disebut satu per satu. Contoh: "
                "CORS_ORIGINS=https://domain-anda.example"
            )
        return value

    @field_validator("access_passcode_sha256")
    @classmethod
    def _validate_passcode_hash(cls, value: str | None) -> str | None:
        """Pastikan yang diisi benar-benar hash SHA-256, bukan passcode mentah.

        Kesalahan yang paling mudah terjadi: operator mengisi passcode
        aslinya, bukan hash-nya. Gejalanya "login selalu gagal" tanpa pesan
        yang menjelaskan, dan penyebabnya sulit terlihat karena nilainya
        memang tampak seperti string biasa.
        """
        if value is None or not value.strip():
            return None
        cleaned = value.strip().lower()
        if len(cleaned) != 64 or not all(c in "0123456789abcdef" for c in cleaned):
            raise ValueError(
                "ACCESS_PASSCODE_SHA256 harus 64 karakter heksadesimal, yaitu "
                "hash SHA-256 dari passcode, BUKAN passcode-nya. Buat dengan: "
                "python -m scripts.make_passcode"
            )
        return cleaned

    @field_validator("llm_fallback_chain")
    @classmethod
    def _validate_fallback(cls, value: list[str]) -> list[str]:
        allowed = {"groq", "ollama", "sglang", "mock"}
        unknown = [item for item in value if item not in allowed]
        if unknown:
            raise ValueError(f"Provider fallback tidak dikenal: {unknown}")
        return value

    # ------------------------------------------------------------- turunan
    @property
    def is_sqlite_mode(self) -> bool:
        """True kalau Supabase tidak dikonfigurasi, lalu pakai SQLite lokal.

        Supabase free-tier/projects lokal sering tidak punya service key, dan
        portofolio harus tetap bisa jalan tanpa satu pun akun cloud.
        """
        return not (self.supabase_url and self.supabase_service_key)

    @property
    def is_memory_store_mode(self) -> bool:
        """True kalau tidak ada Redis/Upstash, lalu pakai dict in-process."""
        return not (self.redis_url or self.upstash_redis_url)

    @property
    def effective_fallback_chain(self) -> list[str]:
        """Rantai provider yang benar-benar akan dicoba.

        Provider aktif selalu jadi percobaan pertama, lalu diikuti rantai
        fallback yang tidak mengulang provider aktif.
        """
        chain = [self.llm_provider, *self.llm_fallback_chain]
        seen: set[str] = set()
        unique: list[str] = []
        for name in chain:
            if name not in seen:
                seen.add(name)
                unique.append(name)
        return unique


@lru_cache
def get_settings() -> Settings:
    """Settings di-cache supaya env dibaca sekali, bukan tiap request."""
    return Settings()
