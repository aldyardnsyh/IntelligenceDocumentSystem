import type { ChatStreamEvent } from "@/types/api";
import { API_BASE_URL } from "./config";
import { ApiError } from "./error";

interface StreamQuery {
  session_id?: string | null;
  question: string;
  document_ids?: string[];
}

export type StreamHandlers = {
  onEvent: (event: ChatStreamEvent) => void;
  signal?: AbortSignal;
};

/**
 * Membaca POST /api/v1/chat/query sebagai SSE.
 * fetch + ReadableStream dipakai (bukan EventSource) karenakjadian/request
 * body, dan EventSource hanya mendukung GET.
 */
export async function streamChatQuery(
  { session_id, question, document_ids }: StreamQuery,
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
      if (done) break;

      buffer += decoder.decode(value, { stream: true });

      // SSE memisahkan event dengan baris kosong ganda.
      let boundary = buffer.indexOf("\n\n");
      while (boundary !== -1) {
        const rawEvent = buffer.slice(0, boundary);
        buffer = buffer.slice(boundary + 2);
        const parsed = parseSseEvent(rawEvent);
        if (parsed) onEvent(parsed);
        boundary = buffer.indexOf("\n\n");
      }
    }
  } finally {
    reader.releaseLock();
  }
}

function parseSseEvent(raw: string): ChatStreamEvent | null {
  const dataLines: string[] = [];

  for (const line of raw.split("\n")) {
    if (line.startsWith("data:")) dataLines.push(line.slice(5).trimStart());
  }

  if (dataLines.length === 0) return null;

  const payload = dataLines.join("\n");
  if (payload === "[DONE]") return { type: "done", response_time_ms: 0 };

  try {
    const parsed = JSON.parse(payload) as ChatStreamEvent;
    return parsed;
  } catch {
    return null;
  }
}
