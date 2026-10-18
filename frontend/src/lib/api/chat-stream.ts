import type { ChatStreamEvent } from "@/types/api";
import { API_BASE_URL } from "./config";
import { ApiError } from "./error";

interface StreamQuery {
  session_id?: string | null;
  question: string;
  document_ids?: string[] | null;
  document_id?: string | null;
  allow_ungrounded?: boolean;
}

export type StreamHandlers = {
  onEvent: (event: ChatStreamEvent) => void;
  signal?: AbortSignal;
};

/**
 * Membaca POST /api/v1/chat/query sebagai SSE.
 * fetch + ReadableStream dipakai (bukan EventSource) karena butuh
 * body/request POST, dan EventSource hanya mendukung GET.
 */
export async function streamChatQuery(
  { session_id, question, document_ids, document_id, allow_ungrounded }: StreamQuery,
  { onEvent, signal }: StreamHandlers,
): Promise<void> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}/api/v1/chat/query`, {
      method: "POST",
      credentials: "include",
      headers: {
        "content-type": "application/json",
        accept: "text/event-stream",
      },
      body: JSON.stringify({
        session_id: session_id ?? null,
        question,
        document_ids: document_ids ?? null,
        document_id: document_id ?? null,
        allow_ungrounded: allow_ungrounded ?? false,
      }),
      signal,
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") return;
    throw new ApiError("Tidak dapat terhubung ke layanan. Periksa koneksi Anda.", 0);
  }

  if (!response.ok) {
    let detail: string | undefined;
    try {
      detail = (await response.json())?.detail;
    } catch {
      detail = undefined;
    }
    const retryAfter = Number.parseInt(response.headers.get("retry-after") ?? "", 10);
    throw new ApiError(
      detail ?? "Permintaan gagal diproses.",
      response.status,
      { retryAfterSeconds: Number.isFinite(retryAfter) ? retryAfter : undefined },
    );
  }

  if (!response.body) {
    throw new ApiError("Server tidak mengirim respons.", 502);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) {
        // Flush decoder tanpa `{stream:true}`: byte terakhir multi-byte bisa
        // masih tertahan di decoder kalau tidak dipaksa keluar.
        buffer += decoder.decode();
        drainSseBuffer(buffer, onEvent);
        break;
      }

      buffer += decoder.decode(value, { stream: true });

      // SSE memisahkan event dengan baris kosong ganda. Pemisahnya bisa
      // `\n\n` atau `\r\n\r\n`; beberapa proxy dan stack Windows memulihkan
      // CRLF, dan satu hop yang begitu membuat seluruh parsing macet.
      for (;;) {
        const match = /\r?\n\r?\n/.exec(buffer);
        if (!match) break;
        const parsed = parseSseEvent(buffer.slice(0, match.index));
        buffer = buffer.slice(match.index + match[0].length);
        if (parsed) onEvent(parsed);
      }
    }
  } finally {
    reader.releaseLock();
  }
}

/**
 * Sisa buffer setelah stream ditutup diproses sebagai satu event terakhir.
 * Tanpa ini, event terakhir hilang kalau server menutup koneksi tanpa
 * baris kosong penutup.
 */
function drainSseBuffer(buffer: string, onEvent: (event: ChatStreamEvent) => void) {
  const trimmed = buffer.trim();
  if (trimmed.length === 0) return;
  const parsed = parseSseEvent(trimmed);
  if (parsed) onEvent(parsed);
}

function parseSseEvent(raw: string): ChatStreamEvent | null {
  const dataLines: string[] = [];

  for (const line of raw.split(/\r?\n/)) {
    if (line.startsWith("data:")) dataLines.push(line.slice(5).trimStart());
  }

  if (dataLines.length === 0) return null;

  const payload = dataLines.join("\n");
  // `[DONE]` adalah penanda akhir dari protokol OpenAI. Backend sudah
  // mengirim event `done` JSON sebelum itu, jadi penanda ini diabaikan:
  // mengubahnya jadi event `done` menimpa `response_time_ms` yang asli.
  if (payload === "[DONE]") return null;

  try {
    const parsed = JSON.parse(payload) as ChatStreamEvent;
    return parsed;
  } catch {
    return null;
  }
}
