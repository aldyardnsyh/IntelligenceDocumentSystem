/**
 * Kontrak API frontend <-> backend FastAPI.
 * Cerminan langsung tabel endpoint di PRD/SRS Section 6.8.
 * Kalau backend berubah, ubah file ini dulu, lalu komponennya.
 */

/** Status ingestion dokumen (FR-1.3). */
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
  /** cuplikan pendek, bukan kutipan penuh (design.md 4.4) */
  excerpt: string;
  score: number;
}

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  created_at: string;
  citations: Citation[];
  /** true bila retrieval tidak melewati similarity threshold (FR-2.3) */
  not_found?: boolean;
}

export interface ChatSession {
  id: string;
  title: string;
  created_at: string;
  last_active_at: string;
  message_count: number;
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
  /** null = belum ada run evaluasi (TC-12) */
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
}

export interface ApiErrorBody {
  detail: string;
  code?: string;
}
