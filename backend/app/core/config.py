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

LlmProviderName = Literal["groq", "openai_compatible", "ollama", "sglang", "mock"]


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
    """Mode akses terbuka untuk demo publik.

    Saat aktif, backend menerbitkan sesi otomatis untuk setiap pengunjung
    (middleware ``open_access`` di ``main.py``) dan verifikasi passcode
    menerima siapa pun. Gate frontend juga dilewati lewat
    ``NEXT_PUBLIC_OPEN_MODE=1``. Semua logika keamanan tidak dihapus, hanya
    di-jembatani, jadi mematikan env ini mengembalikan gate seperti semula.
    """
    auth_open_mode: bool = False
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
    """Model Groq, overrides ``llm_model`` bila diisi.

    Perlu karena rantai fallback memakai provider BERBEDA dengan katalog model
    BERBEDA: ``LLM_MODEL`` bisa menunjuk model provider primary (katalog
    berbeda) sementara fallback Groq memakai model Groq. Tanpa override ini,
    fallback memakai nama model primary yang tidak ada di Groq dan rantai gagal
    di tengah jalan.
    """
    groq_model: str | None = None

    # ------------------------------------------------- openai-compatible
    """Endpoint OpenAI-compatible milik sendiri (router/agregator/proxy).

    Dipakai sebagai provider generation alternatif tanpa mengubah kode di
    atasnya: kontraknya persis protokol OpenAI. ``OPENAI_COMPATIBLE_BASE_URL``
    wajib diisi saat provider ini dipakai.
    """
    openai_compatible_api_key: str | None = None
    openai_compatible_base_url: str | None = None

    ollama_base_url: str = "http://localhost:11434/v1"
    ollama_model: str = "qwen2.5:3b"

    sglang_base_url: str = "http://localhost:30000/v1"
    sglang_model: str = "qwen2.5-3b-instruct"

    # ------------------------------------------------- vision / OCR multimodal
    """Cara PDF diproses: ``auto``, ``text``, atau ``vision``.

    ``auto`` menilai kualitas text-layer PDF (lihat
    ``app.services.ingestion.text_quality``). Text-layer yang utuh dipakai
    apa adanya; yang rusak — seperti PDF Lembaran Negara dari BPK yang
    text-layer OCR-nya kacau urutan bacanya — diganti dengan ekstraksi lewat
    model vision. ``vision`` memaksa semua PDF lewat OCR, ``text`` mematikan
    OCR sepenuhnya.
    """
    ingest_pdf_mode: Literal["auto", "text", "vision"] = "auto"
    """Provider yang menjalankan OCR. Bukan harus sama dengan provider generation:
    OCR butuh model multimodal, bukan model yang paling murah untuk chat."""
    vision_provider: LlmProviderName = "groq"
    """Model multimodal untuk OCR. ``meta-llama/llama-4-scout`` tersedia di free
    tier Groq dan cukup akurat untuk teks cetak Indonesia."""
    vision_model: str = "meta-llama/llama-4-scout-17b-16e-instruct"
    """OCR harus deterministik: temperatur 0, bukan temperatur chat."""
    vision_temperature: float = 0.0
    """Satu halaman A4 padat bisa 1.500+ token; jangan diwarisi batas chat."""
    vision_max_tokens: int = 2048
    """Vision lebih lambat dari chat; timeout-nya sendiri, bukan yang 30 detik."""
    vision_timeout_seconds: float = 90.0
    """Skala render halaman ke gambar. 3.0 = 216 DPI untuk halaman 72 DPI.

    Di 144 DPI PP-OCR kerap menyatukan teks rapat tanpa spasi
    ("Tahun2008Nomor"), dan kata yang menyatu pecah di BM25 maupun embedding.
    Biayanya gambar ~2x lebih besar dan OCR sedikit lebih lambat; masih jauh
    lebih murah daripada mengirim semua halaman ke model vision."""
    pdf_render_scale: float = 3.0
    """Jeda antar halaman saat OCR. Free tier Groq membatasi token per menit,
    dan 14 halaman sekali unggah bisa menghabiskan jatah itu sekaligus.
    Menyerahkan halaman satu per satu dengan jeda lebih baik daripada kena 429
    beruntun."""
    ocr_request_delay_seconds: float = 1.0
    """Percobaan ulang per halaman saat provider kena rate limit."""
    ocr_max_retries: int = 2

    # ------------------------------------------------- prompt injection guard
    """Penyaringan anti-prompt-injection dengan classifier khusus.

    Aturan 14-16 di SYSTEM_PROMPT hanya bertahan di level model; classifier
    ``llama-prompt-guard-2-86m`` (86M parameter, ctx 512) menilai SETIAP konten
    yang akan masuk prompt dan memberi skor risiko 0..1. Konten dengan skor di
    atas ambang diblokir keluar dari konteks dan tidak disitasi — dokumen
    berisi instruksi terselubung ("abaikan aturan sebelumnya") tidak pernah
    sampai ke model generasi.

    Screening dijalankan paralel per chunk saat query (fail-open: kegagalan
    classifier tidak menjatuhkan jawaban), dan otomatis nonaktif saat provider
    tidak tersedia.
    """
    prompt_guard_enabled: bool = True
    prompt_guard_model: str = "meta-llama/llama-prompt-guard-2-86m"
    """Skor risiko (0..1) di atas ambang ini memblokir chunk dari konteks.
    0.5 seimbang: injection nyata skor 0.9+, teks legal normal 0.0-0.1."""
    prompt_guard_threshold: float = 0.5
    """Mesin OCR untuk halaman yang ditandai perlu ekstraksi:

    - ``auto``   : PP-OCR lokal (RapidOCR) utama; halaman dengan confidence
                   rendah dieskalasi ke model vision (butuh VISION_PROVIDER).
    - ``paddle`` : PP-OCR lokal saja, tanpa eskalasi, tanpa biaya API.
    - ``vision`` : model vision untuk semua halaman (perilaku lama).

    Mesin lokal memakai model PP-OCR (RapidOCR/ONNX) dan memulihkan urutan
    baca dua kolom dari bounding box, hal yang tidak bisa dilakukan
    text-layer rusak maupun model vision tanpa biaya per halaman.
    """
    ocr_engine: Literal["auto", "paddle", "vision"] = "auto"
    """Ambang confidence rata-rata halaman di bawahnya halaman dieskalasi ke
    model vision. PP-OCR yang percaya diri tidak perlu dikirim ke API; halaman
    pindai buruk (noda, miring, terlipat) yang perlu diselamatkan."""
    ocr_vlm_rescue_confidence: float = 0.55
    """Pass kedua OCR: celah vertikal besar antar baris di-crop dan dibaca
    ulang dengan zoom 2x. Baris yang tertutup cap tinta Lembaran Negara kerap
    lolos dari detektor pada citra utuh tapi terbaca pada crop zoom. Biayanya
    kecil (maksimal 4 band per halaman); tanpa ini angka penting dalam satu
    baris hilang diam-diam dari korpus."""
    ocr_gap_rescan_enabled: bool = True
    """Voting lintas varian praproses untuk mesin lokal.

    Setiap halaman dibaca lewat beberapa varian citra (as-is, CLAHE, adaptive
    threshold), teks tiap varian di-vote berdasarkan kecocokan. Satu tahap
    tunggal sering salah satu-dua huruf pada pindai buruk dan tetap percaya
    diri; varian berbeda jarang salah di tempat yang sama, jadi mayoritas
    mengembalikan kata yang benar. Halaman yang as-is sudah baik berhenti setelah
    varian pertama (early exit), jadi halaman bersih tidak membayar biaya
    varian ekstra."""
    ocr_variant_voting_enabled: bool = True
    """Koreksi salah-OCR berbasis leksikon korpus (pass level dokumen).

    Kata yang muncul >= 3 kali di dokumen yang sama dianggap dibaca benar;
    token yang tidak ada di kamus tapi bentuk kanoniknya (c~e, l~i, rn~m,
    cl~d — huruf yang lazim tertukar saat pemindaian cetak) bertabrakan
    dengan kata kamus, dikoreksi. Ini satu-satunya koreksi typo di pipeline:
    aman karena di-gate frekuensi dan hanya menyentuh token >= 4 huruf, dan
    korpus legal memang repetitif sehingga kamusnya padat. Matikan bila
    dokumen sangat pendek (kamusnya sempit, risiko salah koreksi naik)."""
    ocr_typo_correction_enabled: bool = True
    """Perbaikan penanda butir/ayat yang rusak (pass level dokumen, lintas
    halaman): penanda butir dua huruf ("Cc." untuk "c.") dipulihkan dari
    urutan abjad, nomor daftar definisi yang hilang dipulihkan dari pola
    barisnya, dan tanda baca akhir butir/ayat dirapikan dari penanda
    berikutnya. Tanpa ini, ayat/butir yang rusak penandanya bocor dari
    chunking struktur dan sitasinya salah pasal."""
    ocr_repair_markers_enabled: bool = True
    """Chunk visual multimodal: lambang, tanda tangan, stempel, dan paraf
    yang terdeteksi di halaman pindai dijadikan chunk terindeks dengan
    caption template (jenis + posisi + teks terdekat). Butuh OpenCV (opsional
    di instalasi); tanpa itu deteksi dilewati diam-diam. Caption VLM
    (deskripsi semantik) belum dipasang — template sudah cukup menjawab
    pertanyaan "lambang apa di kop" / "siapa yang bermaterai".
    """
    ocr_visual_chunks_enabled: bool = True

    # ------------------------------------------------------------- embedding
    """Model embedding lokal (nol biaya, data tidak keluar).

    Default ``multilingual-e5-base``: recall untuk parafrase Bahasa Indonesia
    naik terukur dibanding ``-small``, dengan latensi query yang tetap di
    bawah 100 ms di CPU. Model Inggris-first seperti all-MiniLM-L6-v2
    menghasilkan vektor yang jauh lebih buruk untuk Bahasa Indonesia.
    Mengganti model mengubah dimensi vektor; Chroma akan menandai signature
    mismatch dan isi lama harus diindeks ulang (``python -m scripts.reindex``).
    """
    embedding_model: str = "intfloat/multilingual-e5-base"
    embedding_dimension: int = 768
    embedding_batch_size: int = 16
    """Diaktifkan hanya kalau env ``USE_LOCAL_EMBEDDING=0``; test memakai stub."""
    use_local_embedding: bool = True

    # ------------------------------------------------------------- chunking
    chunk_size: int = 500
    chunk_overlap: int = 50
    """Chunking mengikuti struktur dokumen hukum (BAB/Bagian/Pasal) kalau
    terdeteksi. Batas paragraf generik menghasilkan chunk yang mulai dan
    berakhir di tengah kalimat pada dokumen legal — struktur Pasal adalah
    unit makna alaminya, dan setiap chunk yang mengabaikannya merusak sitasi.
    Dokumen tanpa struktur hukum tetap memakai jalur paragraf lama."""
    legal_chunking_enabled: bool = True
    """Batas karakter isi satu chunk legal sebelum dipecah lagi di batas
    ayat/butir. Lebih besar dari ``chunk_size`` karena satu Pasal adalah satu
    unit makna; memecahnya di tengah ayat menghilangkan konteks rujukan
    "ayat (2)" yang sering dirujuk silang antar Pasal."""
    legal_chunk_max_chars: int = 900

    # -------------------------------------------------------------- retrieval
    default_top_k: int = 5
    min_top_k: int = 3
    max_top_k: int = 10
    # Rentang di sini adalah sumber kebenaran; slider di frontend harus
    # mengikuti angka yang sama.
    #
    # Angka ini diukur, bukan ditebak. Dengan `multilingual-e5-base`, pertanyaan
    # yang benar-benar relevan skornya sekitar 0.85+, yang tidak relevan jauh
    # lebih rendah daripada hasil -small. Ambang diturunkan dari 0.82 ke 0.78
    # supaya pertanyaan parafrase yang relevan tidak tergerus gate, dan
    # kasus "hampir cukup" diserahkan ke tier bukti lemah di RagService,
    # bukan ditolak keras.
    default_similarity_threshold: float = 0.78
    min_similarity_threshold: float = 0.70
    max_similarity_threshold: float = 0.92
    """Bar bukti LEXIKAL MURNI untuk lolos tier jawaban kuat.

    Sebuah chunk dianggap bukti kuat kalau skor vektornya mencapai
    ``default_similarity_threshold`` ATAU skor BM25 ternormalisasi ``s/(s+k)``
    mencapai bar ini. Dua bar yang berbeda karena keduanya mengukur hal yang
    berbeda: kemiripan makna vs kecocokan kata. Versi lama memakai satu
    ambang untuk keduanya (0.78 ≈ BM25 mentah 11.6), sehingga satu-dua kata
    kunci yang cocok sudah cukup menjawab tanpa label — gejala "asal ada
    kata kuncinya, langsung dijawab".

    0.85 ≈ BM25 mentah 22.7 pada ``BM25_SATURATION=4.0``: kecocokan leksikal
    yang benar-benar spesifik (nomor klausul, istilah unik dokumen). Kecocokan
    di bawah bar ini tetap bisa dijawab — lewat tier bukti lemah
    (``weak_evidence_floor``), berlabel jujur. Kalibrasi ulang hanya lewat
    evaluasi (``/analytics/evaluate``), bukan tebakan.
    """
    keyword_strong_bar: float = 0.85
    """Toleransi typo pada pencarian kata (BM25): token query ≥ 6 huruf yang
    tidak ditemukan di indeks dicocokkan fuzzy ke kata indeks terdekat (edit
    distance ≤ 1, maks 3 kandidat per token, bobot 0.8). Dokumen legal banyak
    istilah teknisnya ("penelaahan", "pengklasifikasian") yang mudah salah tik
    oleh pengguna; tanpa toleransi ini, satu huruf yang salah membuat jalur
    kata kunci kosong. Vektor menangkap sebagian, tapi nomor klausul dan
    istilah unik memang jalurnya leksikal."""
    bm25_fuzzy_enabled: bool = True
    """Floor skor vektor untuk tier bukti lemah.

    Kalau gate ambang menolak semua kandidat tapi masih ada yang skornya di
    atas floor ini, pertanyaan tetap dijawab dengan label bukti terbatas,
    bukan ditolak keras. Di bawah floor, jawaban hampir pasti bukan tentang
    dokumen, dan menolak adalah perilaku yang benar.
    """
    weak_evidence_floor: float = 0.60
    """Berapa chunk tetangga (chunk_index ± N) dari dokumen yang sama ikut ke
    prompt sebagai konteks sekitar. Ayat dan butir sering dirujuk silang ke
    Pasal di sebelahnya; tanpa konteks ini, LLM melihat Pasal 5 tanpa tahu
    isi Pasal 4. Tetangga tidak ikut disitasi."""
    context_window_chunks: int = 1
    """Batas karakter total blok konteks di prompt (termasuk konteks sekitar).
    Tanpa batas, dokumen padat dengan top_k besar bisa menelan window model."""
    max_context_chars: int = 8000
    """Berapa pesan terakhir yang ikut sebagai konteks."""
    history_message_count: int = 6
    """Reranking dua tahap dengan cross-encoder multilingual.

    Ambang tunggal tidak bisa memisahkan sempurna: skor cosine chunk benar dan
    salah tumpang tindih. Reranking menilai ulang kandidat memakai cross-encoder
    yang membaca pertanyaan dan chunk bersamaan.

    ``BAAI/bge-reranker-v2-m3`` dipilih karena multilingual (100+ bahasa,
    termasuk Indonesia) dan berlisensi Apache-2.0. Model Inggris
    ms-marco-MiniLM praktis tidak berguna untuk query Indonesia. Biayanya
    sekitar 1.1 GB RAM dan 150-400 ms per query di CPU; kegagalan memuat
    model tidak menjatuhkan aplikasi (fallback ke urutan fusion).
    """
    rerank_enabled: bool = True
    rerank_model: str = "BAAI/bge-reranker-v2-m3"
    """Perangkat inferensi reranker. ``cpu`` aman untuk semua server; ``cuda``
    untuk VPS/GPU box."""
    rerank_device: str = "cpu"
    """Berapa kandidat yang diambil sebelum diurutkan ulang.

    Lebih banyak berarti peluang chunk benar masuk kandidat lebih besar, tapi
    cross-encoder harus menilai setiap pasangan, dan biayanya naik linear.
    Nilai ini juga menentukan kedalaman pool kandidat retrieval (sebelumnya
    setting ini terbaca tapi tidak pernah dipakai).
    """
    rerank_candidates: int = 8
    """Stemming Sastrawi pada token BM25. ``pengaduan``, ``mengadu``, dan
    ``diadukan`` semuanya jadi ``adu``, jadi pertanyaan yang memakai kata
    bentuk lain tetap menemukan chunk yang memakai istilah dokumen. Karena
    dipakai seragam di dokumen dan query, hasilnya tetap konsisten."""
    bm25_stemming_enabled: bool = True
    """Cache query: TTL dan key."""
    cache_ttl_seconds: int = 30 * 60
    """Rate limit query per sesi, untuk melindungi kuota free tier."""
    query_max_per_session: int = 20
    query_window_seconds: int = 60
    """Berapa hari log query disimpan sebelum dibersihkan.

    Tanpa ini, tabel ``query_logs`` tumbuh terus dan dashboard mulai
    memotong data lama secara diam-diam: angka latency dan token hanya
    mencerminkan sebagian riwayat, tanpa tanda apa pun bahwa itu terjadi.

    Dibersihkan saat startup, bukan lewat cron, karena satu instance dengan
    satu kali jalan per deploy sudah cukup untuk menjaga tabelnya wajar.
    Set 0 untuk mematikan pembersihan dan menyimpan log selamanya.
    """
    query_log_retention_days: int = 90

    # ------------------------------------------------------------- documents
    max_file_size_bytes: int = 10 * 1024 * 1024
    accepted_extensions: list[str] = Field(
        default_factory=lambda: [".pdf", ".txt", ".md", ".markdown"]
    )
    """Batas jumlah dokumen yang bisa disimpan sekaligus.

    Batas per berkas (10 MB) tidak menutup apa pun kalau jumlah berkasnya
    tidak dibatasi. Satu pengguna bisa mengunggah ratusan berkas sampai disk
    server penuh, dan itu terjadi setelah deployment, bukan saat
    pengembangan.

    200 dokumen terasa longgar untuk pemakaian nyata, dan cukup kecil untuk
    tidak menghabiskan disk 20 GB. Naikkan kalau memang perlu; angkanya
    sengaja di satu tempat supaya tidak tersebar.
    """
    max_documents: int = 200
    """Batas total ukuran seluruh dokumen yang disimpan, dalam byte.

    Batas jumlah saja belum cukup: 200 berkas berukuran 10 MB berarti 2 GB.
    Batas ini menjaga pemakaian disk tetap terprediksi, termasuk untuk
    berkas asli yang disimpan demi pratinjau PDF. Default 1 GB.
    """
    max_total_document_bytes: int = 1024 * 1024 * 1024
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
        allowed = {"groq", "openai_compatible", "ollama", "sglang", "mock"}
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

    def rate_limit_identity(self) -> str:
        """Identitas stabil untuk kunci rate limit.

        Kenapa bukan token sesi: token berubah setiap kali pengguna login
        ulang, sehingga bucket ikut baru dan kuota bisa dilewati hanya
        dengan logout lalu masuk lagi.

        Kenapa hash passcode: aplikasi ini memakai satu passcode, jadi semua
        sesi sah berasal dari kredensial yang sama. Hash-nya stabil lintas
        login, dan karena yang dipakai hash, nilainya aman kalau ikut
        tercatat di log atau di store.

        Kalau nanti ada multi-pengguna, fungsi ini yang diganti: kembalikan
        id pengguna, bukan hash passcode.
        """
        if not self.access_passcode_sha256:
            # Tidak mungkin terjadi pada request yang lolos ``require_session``,
            # karena tanpa passcode tidak ada sesi yang bisa diterbitkan.
            # Nilai cadangan ini menjaga fungsi tetap deterministik.
            return "tanpa-passcode"
        return self.access_passcode_sha256

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
