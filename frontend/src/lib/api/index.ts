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
import { API_BASE_URL } from "./config";
import { ApiError } from "./error";
import { request } from "./http";

/* --------------------------------------------------------------------------
   Satu pintu masuk untuk semua halaman. Halaman tidak boleh tahu apakah dia
   berbicara ke FastAPI atau ke fixture lokal.
--------------------------------------------------------------------------- */

/* ------------------------------- documents -------------------------------- */

export function listDocuments(signal?: AbortSignal) {
  return request<DocumentSummary[]>("/api/v1/documents", { signal });
}

export function getDocument(id: string, signal?: AbortSignal) {
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
  return request<DocumentPreview>(`/api/v1/documents/${id}/preview`, { signal });
}

/**
 * URL berkas asli dokumen, untuk pratinjau PDF di iframe.
 *
 * Dikembalikan sebagai URL (bukan diambil lewat fetch) karena browser yang
 * harus memuatnya: PDF ditampilkan oleh penampil bawaan browser, dan
 * mengunduhnya lewat fetch lalu membuat blob hanya menambah satu salinan
 * besar di memori tanpa manfaat.
 *
 * Di mode demo tidak ada endpoint berkas: sumbernya blob yang dibuat saat
 * unggah dan hanya hidup selama sesi. Karena itu hasilnya bisa string kosong
 * setelah muat ulang — pemanggil wajib menanganinya, bukan merender iframe
 * dengan src kosong.
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

export interface UploadOptions {
  signal?: AbortSignal;
  /**
   * Progres unggahan 0..100, dilaporkan browser untuk byte yang benar-benar
   * terkirim. Ini BUKAN progres pemrosesan di server — setelah 100%, server
   * masih melakukan ekstraksi/OCR yang dilaporkan lewat status kartu dokumen.
   */
  onProgress?: (percent: number) => void;
}

/**
 * Unggah dokumen memakai XHR, bukan fetch.
 *
 * `fetch` tidak bisa melaporkan progres unggahan: janji-nya baru selesai
 * setelah seluruh byte terkirim, sehingga pengguna menatap tombol diam tanpa
 * tahu apakah prosesnya berjalan atau macet. XHR punya `upload.onprogress`,
 * dan UI memakai angka itu untuk progress bar.
 *
 * Kegagalan jaringan dibedakan dari penolakan server: koneksi mati menghasilkan
 * pesan yang menunjuk ke koneksi/backend, bukan "periksa format berkas" yang
 * menyesatkan bila masalahnya bukan format.
 */
export async function uploadDocument(
  file: File,
  options: UploadOptions = {},
): Promise<DocumentSummary> {
  const { signal, onProgress } = options;
  const form = new FormData();
  form.append("file", file);

  return new Promise<DocumentSummary>((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `${API_BASE_URL}/api/v1/documents/upload`);
    // Signal diteruskan supaya unggahan bisa dibatalkan. Tanpa itu, pengguna
    // yang pindah halaman masih menunggu request yang tidak lagi relevan.
    signal?.addEventListener("abort", () => xhr.abort(), { once: true });

    xhr.upload.onprogress = (event) => {
      if (onProgress && event.lengthComputable) {
        onProgress(Math.round((event.loaded / event.total) * 100));
      }
    };

    xhr.onload = () => {
      let body: unknown = null;
      try {
        body = JSON.parse(xhr.responseText);
      } catch {
        // Respons non-JSON (mis. halaman error proxy) tetap ditangani di bawah.
      }
      if (xhr.status >= 200 && xhr.status < 300) {
        resolve(body as DocumentSummary);
        return;
      }
      const detail =
        (body as { detail?: string } | null)?.detail
        ?? `Server menolak unggahan (HTTP ${xhr.status}).`;
      reject(new ApiError(detail, xhr.status));
    };

    xhr.onerror = () => {
      reject(
        new ApiError(
          "Tidak dapat terhubung ke server. Periksa koneksi, atau coba lagi "
            + "sebentar bila server sedang tidak aktif.",
          0,
        ),
      );
    };

    xhr.onabort = () => {
      reject(new ApiError("Unggahan dibatalkan.", 0));
    };

    xhr.send(form);
  });
}

export async function deleteDocument(id: string) {
  return request<void>(`/api/v1/documents/${id}`, { method: "DELETE" });
}

/* ---------------------------------- chat ---------------------------------- */

export function listSessions(signal?: AbortSignal): Promise<ChatSession[]> {
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
    /** Jawaban dibuat dari bukti di bawah ambang normal (bukti lemah). */
    weak_evidence?: boolean;
  }>;
}

export function getHistory(sessionId: string, signal?: AbortSignal): Promise<HistoryResponse | null> {
  return request<HistoryResponse>(`/api/v1/chat/${sessionId}/history`, { signal });
}

/**
 * Mengubah judul satu sesi. Judul hasil otomatis hanya dipakai sampai user
 * memberi nama sendiri, jadi penulisan ulang ini tidak pernah tertimpa
 * pertanyaan berikutnya.
 */
export async function renameSession(id: string, title: string) {
  return request<ChatSession>(`/api/v1/chat/sessions/${id}`, {
    method: "PATCH",
    body: { title },
  });
}

/** Menghapus satu sesi beserta seluruh pesanannya. */
export async function deleteSession(id: string) {
  return request<void>(`/api/v1/chat/sessions/${id}`, { method: "DELETE" });
}

export async function resetAllSessions() {
  return request<void>("/api/v1/chat/sessions", { method: "DELETE" });
}

export function newSessionId() {
  return `draft_${Math.random().toString(36).slice(2, 10)}`;
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

export async function askQuestion(
  { sessionId, question, documentId, documentIds, allowUngrounded }: AskArgs,
  handlers: AskHandlers,
) {
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

/* -------------------------------- settings -------------------------------- */

export function getSettings(signal?: AbortSignal): Promise<RetrievalSettings> {
  return request<RetrievalSettings>("/api/v1/settings", { signal });
}

export function updateSettings(patch: Partial<RetrievalSettings>) {
  return request<RetrievalSettings>("/api/v1/settings", { method: "PUT", body: patch });
}

/* ------------------------------- analytics -------------------------------- */

export function getAnalyticsSummary(signal?: AbortSignal): Promise<AnalyticsSummary> {
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
  return request<AnalyticsLogs>("/api/v1/analytics/logs", {
    query: { page, page_size: pageSize },
    signal,
  });
}

export function getHealth(signal?: AbortSignal): Promise<HealthStatus> {
  return request<HealthStatus>("/api/v1/health", { signal });
}
