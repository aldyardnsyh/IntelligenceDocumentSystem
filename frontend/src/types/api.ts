/**
 * Kontrak API frontend <-> backend FastAPI.
 * Cerminan kontrak API backend FastAPI (lihat API-CONTRACT.md).
 * Kalau backend berubah, ubah file ini dulu, lalu komponennya.
 */

/** Status ingestion dokumen. */
export type DocumentStatus =
  | "uploading"
  | "processing"
  | "ready"
  | "failed";

export interface DocumentSummary {
  id: string;
  filename: string;
  page_count: number | null;
  size_bytes: number;
  status: DocumentStatus;
  uploaded_at: string;
  /** populated saat status = failed */
  error_message?: string | null;
  /** jumlah chunk hasil ingestion, null selama masih processing */
  chunk_count?: number | null;
}

export interface Chunk {
  id: string;
  document_id: string;
  chunk_index: number;
  page_number: number | null;
  content: string;
  /** token count opsional dari splitter */
  token_count?: number | null;
}

/**
 * Metadata dokumen saja. Chunk diambil terpisah lewat
 * GET /documents/{id}/chunks karena satu dokumen bisa menempel ribuan chunk,
 * dan memuat semuanya sekaligus membuat halaman detail tidak terpakai.
 */
export interface DocumentDetail extends DocumentSummary {
  ingestion: {
    splitter: string;
    chunk_size: number;
    chunk_overlap: number;
    embedding_model: string;
    vector_store: string;
  };
}

/**
 * Isi dokumen yang tersimpan, untuk cross-check jawaban chat.
 *
 * `content` adalah teks hasil parsing, bukan berkas aslinya. `truncated`
 * menandai kalau isinya dipotong.
 */
export interface DocumentPreview {
  id: string;
  filename: string;
  status: DocumentSummary["status"];
  content: string;
  chunk_count: number;
  truncated: boolean;
  preview_chars: number;
  total_chars: number;
}

/** Satu halaman hasil dari GET /documents/{id}/chunks. */
export interface ChunkPage {
  items: Chunk[];
  total: number;
  page: number;
  page_size: number;
}

export interface Citation {
  document_id: string;
  document_name: string;
  page_number: number | null;
  chunk_index: number;
  /** cuplikan pendek, bukan kutipan penuh */
  excerpt: string;
  score: number;
}

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  created_at: string;
  citations: Citation[];
  /** true bila retrieval tidak melewati similarity threshold */
  not_found?: boolean;
  /**
   * true bila jawaban datang dari pengetahuan umum model, bukan dari
   * dokumen. UI wajib menampilkan labelnya, termasuk saat riwayat dibuka
   * ulang.
   */
  ungrounded?: boolean;
}

export interface ChatSession {
  id: string;
  title: string;
  created_at: string;
  last_active_at: string;
  message_count: number;
  /**
   * Dokumen yang mengikat sesi ini, atau `null` untuk sesi lintas dokumen.
   * Sesi ber-scope hanya mencari di dokumen itu.
   */
  document_id?: string | null;
}

export interface RetrievalSettings {
  top_k: number;
  similarity_threshold: number;
}

/** Satu event dari stream SSE POST /chat/query. */
export type ChatStreamEvent =
  | { type: "session"; session_id: string }
  | { type: "token"; value: string }
  | { type: "citations"; value: Citation[] }
  | { type: "not_found" }
  | { type: "ungrounded" }
  | { type: "done"; response_time_ms: number }
  | { type: "error"; message: string; retry_after_seconds?: number };

export interface EvalRun {
  id: string;
  precision: number | null;
  faithfulness: number | null;
  answer_relevance: number | null;
  run_at: string;
}

export interface LatencyPoint {
  /** tanggal dalam format YYYY-MM-DD, selalu UTC */
  date: string;
  avg_ms: number;
  p95_ms: number;
}

export interface TokenPoint {
  /** tanggal dalam format YYYY-MM-DD, selalu UTC */
  date: string;
  input_tokens: number;
  output_tokens: number;
  /**
   * Backend tidak menerima jumlah token dari provider, jadi angkanya
   * estimasi. UI wajib menyebutinya sebagai estimasi, bukan pengukuran.
   */
  estimated?: boolean;
}

export interface QueryLog {
  id: string;
  session_id: string | null;
  question: string;
  response_time_ms: number;
  sources_count: number;
  created_at: string;
  from_cache: boolean;
  /**
   * Id trace Langfuse. null kalau panggilan LLM tidak terjadi, misalnya
   * pertanyaan dijawab dari cache atau retrieval tidak menemukan apa pun.
   * Frontend tidak pernah membuat id ini di sisi klien.
   */
  trace_id: string | null;
}

export interface AnalyticsSummary {
  /** null = belum ada run evaluasi */
  latest_eval: EvalRun | null;
  latency: LatencyPoint[];
  tokens: TokenPoint[];
}

export interface AnalyticsLogs {
  items: QueryLog[];
  total: number;
  page: number;
  page_size: number;
}

export interface HealthStatus {
  status: "ok" | "degraded";
  llm: "ok" | "unreachable";
  vector_store: "ok" | "unreachable";
  memory: "ok" | "unreachable";
  version: string;
  /**
   * Mode fallback yang sedang aktif di backend (API-CONTRACT.md Section 8).
   * `mode: "reduced"` berarti salah satu komponen berjalan non-persisten.
   *
   * Isinya sengaja terbatas. `/health` adalah endpoint publik yang dipanggil
   * sebelum sesi ada (healthcheck, halaman login), jadi nama repository,
   * memory store, provider LLM, dan model embedding tidak dikirim ke sini.
   * Detail itu hanya ada di log server.
   */
  fallback?: {
    vector_store?: string;
    vector_store_persistent?: boolean;
    mode?: "full" | "reduced" | string;
    /**
     * Penanda proses backend. Berubah setiap kali backend dijalankan ulang,
     * dan dipakai frontend untuk membuang state browser yang tersisa dari
     * proses sebelumnya (sesi memori tidak bertahan melewati restart).
     */
    boot_id?: string;
    /**
     * Ada hanya kalau indeks dibangun dengan model embedding yang berbeda
     * dari yang aktif sekarang. Isinya pesan siap tampil, termasuk perintah
     * yang harus dijalankan, jadi frontend tidak perlu menyusun sendiri.
     */
    embedding_mismatch?: string;
  } | null;
}

export interface ApiErrorBody {
  detail: string;
  code?: string;
}
