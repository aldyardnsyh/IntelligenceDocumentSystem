import type {
  AnalyticsLogs,
  AnalyticsSummary,
  ChatSession,
  ChatStreamEvent,
  ChunkPage,
  Citation,
  DocumentDetail,
  DocumentSummary,
  HealthStatus,
  RetrievalSettings,
} from "@/types/api";
import { streamChatQuery } from "./chat-stream";
import { isMockMode } from "./config";
import { ApiError } from "./error";
import { request } from "./http";
import { mockApi } from "@/lib/mock/store";

/* --------------------------------------------------------------------------
   Satu pintu masuk untuk semua halaman. Halaman tidak boleh tahu apakah dia
   berbicara ke FastAPI atau ke fixture lokal.
--------------------------------------------------------------------------- */

/* ------------------------------- documents -------------------------------- */

export function listDocuments(signal?: AbortSignal) {
  if (isMockMode) return mockApi.listDocuments();
  return request<DocumentSummary[]>("/api/v1/documents", { signal });
}

export function getDocument(id: string, signal?: AbortSignal) {
  if (isMockMode) return mockApi.getDocument(id);
  return request<DocumentDetail>(`/api/v1/documents/${id}`, { signal });
}

export interface ChunkQuery {
  page: number;
  pageSize: number;
  /** pencarian isi chunk, di-filter di server supaya tidak perlu unduh semua */
  search?: string;
}

export function getDocumentChunks(
  id: string,
  { page, pageSize, search }: ChunkQuery,
  signal?: AbortSignal,
): Promise<ChunkPage> {
  if (isMockMode) return mockApi.getDocumentChunks(id, { page, pageSize, search });
  return request<ChunkPage>(`/api/v1/documents/${id}/chunks`, {
    query: {
      page,
      page_size: pageSize,
      // Backend/CDN sering mengabaikan query kosong, jadi string kosong tidak
      // ikut dikirim sama sekali.
      q: search && search.trim().length > 0 ? search.trim() : undefined,
    },
    signal,
  });
}

export async function uploadDocument(file: File) {
  if (isMockMode) {
    try {
      return await mockApi.uploadDocument(file);
    } catch (error) {
      const message = error instanceof Error ? error.message : "Unggahan gagal.";
      throw new ApiError(message, (error as { status?: number }).status ?? 400);
    }
  }

  const form = new FormData();
  form.append("file", file);
  return request<DocumentSummary>("/api/v1/documents/upload", {
    method: "POST",
    body: form,
  });
}

export async function deleteDocument(id: string) {
  if (isMockMode) return mockApi.deleteDocument(id);
  return request<void>(`/api/v1/documents/${id}`, { method: "DELETE" });
}

/* ---------------------------------- chat ---------------------------------- */

export function listSessions(signal?: AbortSignal): Promise<ChatSession[]> {
  if (isMockMode) return mockApi.listSessions();
  // Catatan: endpoint ini belum ada di tabel PRD 6.8, tetapi sidebar
  // membutuhkannya. Sudah dicatat sebagai kebutuhan backend.
  return request<ChatSession[]>("/api/v1/chat/sessions", { signal });
}

export interface HistoryResponse {
  session: ChatSession;
  messages: Array<{
    id: string;
    role: "user" | "assistant";
    content: string;
    created_at: string;
    citations: Citation[];
    not_found?: boolean;
  }>;
}

export function getHistory(sessionId: string, signal?: AbortSignal): Promise<HistoryResponse | null> {
  if (isMockMode) return mockApi.getHistory(sessionId);
  return request<HistoryResponse>(`/api/v1/chat/${sessionId}/history`, { signal });
}

/**
 * Mengubah judul satu sesi. Judul hasil otomatis hanya dipakai sampai user
 * memberi nama sendiri, jadi penulisan ulang ini tidak pernah tertimpa
 * pertanyaan berikutnya.
 */
export async function renameSession(id: string, title: string) {
  if (isMockMode) return mockApi.renameSession(id, title);
  return request<ChatSession>(`/api/v1/chat/sessions/${id}`, {
    method: "PATCH",
    body: { title },
  });
}

/** Menghapus satu sesi beserta seluruh pesanannya. */
export async function deleteSession(id: string) {
  if (isMockMode) return mockApi.deleteSession(id);
  return request<void>(`/api/v1/chat/sessions/${id}`, { method: "DELETE" });
}

export async function resetAllSessions() {
  if (isMockMode) return mockApi.resetSessions();
  return request<void>("/api/v1/chat/sessions", { method: "DELETE" });
}

export function newSessionId() {
  return isMockMode
    ? mockApi.createSessionId()
    : `draft_${Math.random().toString(36).slice(2, 10)}`;
}

export function titleFrom(question: string) {
  const trimmed = question.trim().replace(/\s+/g, " ");
  return trimmed.length > 60 ? `${trimmed.slice(0, 60)}...` : trimmed;
}

export interface AskHandlers {
  onEvent: (event: ChatStreamEvent) => void;
  signal?: AbortSignal;
}

export interface AskArgs {
  sessionId: string | null;
  question: string;
}

/**
 * Fixture meniru SSE dengan menunda token per beberapa karakter, sehingga
 * indikator streaming, tombol stop, dan state "menjawab" bisa dicoba tanpa
 * backend. Bentuk event-nya sama persis dengan FastAPI.
 */
export async function askQuestion({ sessionId, question }: AskArgs, handlers: AskHandlers) {
  if (!isMockMode) {
    return streamChatQuery(
      { session_id: sessionId, question },
      { onEvent: handlers.onEvent, signal: handlers.signal },
    );
  }

  const session = sessionId ?? mockApi.createSessionId();
  const startedAt = Date.now();
  const emit = (event: ChatStreamEvent) => handlers.onEvent(event);

  await delay(200, handlers.signal);
  if (handlers.signal?.aborted) return;

  emit({ type: "session", session_id: session });

  const result = mockApi.compose(question);

  mockApi.appendMessage(session, {
    role: "user",
    content: question,
    citations: [],
    not_found: false,
  });

  if (result.notFound) {
    await delay(300, handlers.signal);
    if (handlers.signal?.aborted) return;

    const message =
      "Informasi ini tidak ditemukan dalam dokumen yang diunggah. "
      + "Coba dengan istilah yang dipakai di dalam dokumen, atau periksa daftar dokumen.";
    emit({ type: "not_found" });
    mockApi.appendMessage(session, {
      role: "assistant",
      content: message,
      citations: [],
      not_found: true,
    });
    const elapsed = Date.now() - startedAt;
    void mockApi.recordLog({
      id: makeLogId(),
      session_id: session,
      question,
      response_time_ms: elapsed,
      sources_count: 0,
      created_at: new Date().toISOString(),
      from_cache: false,
      // Mode fixture tidak memanggil LLM, jadi tidak ada trace Langfuse yang
      // bisa dirujuk. null lebih jujur daripada id dipakai.
      trace_id: null,
    });
    emit({ type: "done", response_time_ms: elapsed });
    return;
  }

  for (let index = 0; index < result.text.length; index += 4) {
    if (handlers.signal?.aborted) return;
    emit({ type: "token", value: result.text.slice(index, index + 4) });
    await delay(16, handlers.signal);
  }
  if (handlers.signal?.aborted) return;

  emit({ type: "citations", value: result.citations });
  mockApi.appendMessage(session, {
    role: "assistant",
    content: result.text,
    citations: result.citations,
    not_found: false,
  });

  const elapsed = Date.now() - startedAt;
  void mockApi.recordLog({
    id: makeLogId(),
    session_id: session,
    question,
    response_time_ms: elapsed,
    sources_count: result.citations.length,
    created_at: new Date().toISOString(),
    from_cache: false,
    trace_id: null,
  });
  emit({ type: "done", response_time_ms: elapsed });
}

function makeLogId() {
  return `log_${Math.random().toString(36).slice(2, 10)}`;
}

function delay(ms: number, signal?: AbortSignal) {
  return new Promise<void>((resolve) => {
    const timer = setTimeout(resolve, ms);
    signal?.addEventListener(
      "abort",
      () => {
        clearTimeout(timer);
        resolve();
      },
      { once: true },
    );
  });
}

/* -------------------------------- settings -------------------------------- */

export function getSettings(signal?: AbortSignal): Promise<RetrievalSettings> {
  if (isMockMode) return mockApi.getSettings();
  return request<RetrievalSettings>("/api/v1/settings", { signal });
}

export function updateSettings(patch: Partial<RetrievalSettings>) {
  if (isMockMode) return mockApi.updateSettings(patch);
  return request<RetrievalSettings>("/api/v1/settings", { method: "PUT", body: patch });
}

/* ------------------------------- analytics -------------------------------- */

export function getAnalyticsSummary(signal?: AbortSignal): Promise<AnalyticsSummary> {
  if (isMockMode) return Promise.resolve(mockApi.analyticsSummary());
  return request<AnalyticsSummary>("/api/v1/analytics/summary", { signal });
}

export function getAnalyticsLogs(
  page: number,
  pageSize: number,
  signal?: AbortSignal,
): Promise<AnalyticsLogs> {
  if (isMockMode) return Promise.resolve(mockApi.analyticsLogs(page, pageSize));
  return request<AnalyticsLogs>("/api/v1/analytics/logs", {
    query: { page, page_size: pageSize },
    signal,
  });
}

export function getHealth(signal?: AbortSignal): Promise<HealthStatus> {
  if (isMockMode) {
    return Promise.resolve<HealthStatus>({
      status: "degraded",
      llm: "unreachable",
      vector_store: "unreachable",
      memory: "unreachable",
      version: "fixture lokal",
    });
  }
  return request<HealthStatus>("/api/v1/health", { signal });
}
