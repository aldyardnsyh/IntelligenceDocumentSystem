import type {
  AnalyticsLogs,
  AnalyticsSummary,
  ChatSession,
  ChatStreamEvent,
  ChunkPage,
  Citation,
  DocumentDetail,
  DocumentPreview,
  DocumentSummary,
  EvalRun,
  HealthStatus,
  RetrievalSettings,
} from "@/types/api";
import { streamChatQuery } from "./chat-stream";
import { API_BASE_URL, isMockMode } from "./config";
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

/**
 * Isi dokumen yang tersimpan, untuk cross-check jawaban chat.
 *
 * Halaman dokumen perlu menampilkan teks aslinya berurutan: daftar chunk
 * terpisah-pisah menyembunyikan konteks di sekitarnya, sehingga pengguna
 * tidak bisa menilai apakah jawaban chat benar.
 */
export function getDocumentPreview(id: string, signal?: AbortSignal) {
  if (isMockMode) return mockApi.getDocumentPreview(id);
  return request<DocumentPreview>(`/api/v1/documents/${id}/preview`, { signal });
}

/**
 * URL berkas asli dokumen, untuk pratinjau PDF di iframe.
 *
 * Dikembalikan sebagai URL (bukan diambil lewat fetch) karena browser yang
 * harus memuatnya: PDF ditampilkan oleh penampil bawaan browser, dan
 * mengunduhnya lewat fetch lalu membuat blob hanya menambah satu salinan
 * besar di memori tanpa manfaat.
 */
export function getDocumentFileUrl(id: string): string {
  return `${API_BASE_URL}/api/v1/documents/${id}/file`;
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

export async function uploadDocument(file: File, signal?: AbortSignal) {
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
  // Signal diteruskan supaya unggahan bisa dibatalkan. Tanpa itu, pengguna
  // yang pindah halaman masih menunggu request yang tidak lagi relevan.
  return request<DocumentSummary>("/api/v1/documents/upload", {
    method: "POST",
    body: form,
    signal,
  });
}

export async function deleteDocument(id: string) {
  if (isMockMode) return mockApi.deleteDocument(id);
  return request<void>(`/api/v1/documents/${id}`, { method: "DELETE" });
}

/* ---------------------------------- chat ---------------------------------- */

export function listSessions(signal?: AbortSignal): Promise<ChatSession[]> {
  if (isMockMode) return mockApi.listSessions();
  // Catatan: endpoint ini dipakai sidebar, jadi harus tetap ada
  // walau tidak muncul di tabel kontrak API.
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
    /** Jawaban dari pengetahuan umum model, bukan dari dokumen. */
    ungrounded?: boolean;
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
  /** Scope dokumen untuk sesi ini (chat privat per dokumen). */
  documentId?: string | null;
  /**
   * Beberapa dokumen sekaligus sebagai scope. Daftar kosong berarti semua
   * dokumen. Kalau `documentId` juga diberi, backend memakai `documentId`
   * karena itu scope yang lebih sempit.
   */
  documentIds?: string[] | null;
  /** Izinkan jawaban dari pengetahuan umum saat tidak ada konteks dokumen. */
  allowUngrounded?: boolean;
}

/**
 * Fixture meniru SSE dengan menunda token per beberapa karakter, sehingga
 * indikator streaming, tombol stop, dan state "menjawab" bisa dicoba tanpa
 * backend. Bentuk event-nya sama persis dengan FastAPI.
 */
export async function askQuestion(
  { sessionId, question, documentId, documentIds, allowUngrounded }: AskArgs,
  handlers: AskHandlers,
) {
  if (!isMockMode) {
    // `draft_...` hanya penanda "belum ada sesi di server". Kalau id itu
    // diteruskan apa adanya, backend akan memperlakukannya sebagai sesi
    // yang sudah ada padahal belum pernah dibuat.
    const resolved = sessionId && !sessionId.startsWith("draft_") ? sessionId : null;
    return streamChatQuery(
      {
        session_id: resolved,
        question,
        document_id: documentId ?? null,
        // Daftar kosong dikirim sebagai null, bukan `[]`: backend membaca
        // keduanya sebagai "tanpa scope", dan null lebih jelas maksudnya.
        document_ids: documentIds && documentIds.length > 0 ? documentIds : null,
        allow_ungrounded: allowUngrounded ?? false,
      },
      { onEvent: handlers.onEvent, signal: handlers.signal },
    );
  }

  const session = sessionId && !sessionId.startsWith("draft_") ? sessionId : mockApi.createSessionId();
  const startedAt = Date.now();
  const emit = (event: ChatStreamEvent) => handlers.onEvent(event);

  await delay(200, handlers.signal);
  if (handlers.signal?.aborted) return;

  emit({ type: "session", session_id: session });

  const result = mockApi.compose(question, documentId ?? null);

  mockApi.appendMessage(
    session,
    {
      role: "user",
      content: question,
      citations: [],
      not_found: false,
    },
    documentId ?? null,
  );

  if (result.notFound) {
    await delay(300, handlers.signal);
    if (handlers.signal?.aborted) return;

    // Mode "jawab tanpa dokumen" juga berlaku di fixture, supaya perilaku
    // kedua mode tidak berbeda.
    if (allowUngrounded) {
      const answer =
        "Ini bukan dari dokumen Anda: menurut pengetahuan umum, jawaban "
        + "untuk pertanyaan itu tidak tersedia di korpus yang diunggah, dan "
        + "mode demo tidak memiliki model untuk menjawabnya.";
      emit({ type: "ungrounded" });
      for (const piece of answer.match(/.{1,24}/g) ?? []) {
        await delay(40, handlers.signal);
        if (handlers.signal?.aborted) return;
        emit({ type: "token", value: piece });
      }
      mockApi.appendMessage(session, {
        role: "assistant",
        content: answer,
        citations: [],
        not_found: false,
      });
      const elapsed = Date.now() - startedAt;
      emit({ type: "done", response_time_ms: elapsed });
      return;
    }

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

/**
 * Jalankan evaluasi retrieval (tanpa LLM, tanpa API key).
 *
 * Halaman /analytics sebelumnya hanya bisa diisi lewat skrip RAGAS yang
 * butuh kredensial tambahan. Endpoint ini menghitung metrik yang bisa
 * dijawab tanpa model, sehingga halaman itu punya jalan keluar sendiri.
 */
export function runRetrievalEvaluation(documentIds: string[] = []): Promise<EvalRun> {
  if (isMockMode) {
    return Promise.reject(
      new ApiError("Evaluasi hanya tersedia saat backend aktif.", 400),
    );
  }
  return request<EvalRun>("/api/v1/analytics/evaluate", {
    method: "POST",
    body: { document_ids: documentIds },
  });
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
      // Bentuknya disamakan dengan respons backend sungguhan, termasuk
      // batasnya: nama komponen internal tidak dikirim lewat /health.
      fallback: {
        vector_store: "fixture",
        vector_store_persistent: false,
        mode: "reduced",
      },
    });
  }
  return request<HealthStatus>("/api/v1/health", { signal });
}
