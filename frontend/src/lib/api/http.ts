import { API_BASE_URL } from "./config";
import { ApiError, messageForStatus, parseErrorBody } from "./error";

type QueryValue = string | number | boolean | undefined | null;

function buildUrl(path: string, query?: Record<string, QueryValue>) {
  const url = `${API_BASE_URL}${path}`;
  if (!query) return url;

  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value === undefined || value === null || value === "") continue;
    params.set(key, String(value));
  }

  const qs = params.toString();
  return qs ? `${url}?${qs}` : url;
}

async function readError(response: Response): Promise<ApiError> {
  let body: unknown = null;
  try {
    body = await response.json();
  } catch {
    body = null;
  }

  const parsed = parseErrorBody(body);
  const retryAfterHeader = response.headers.get("retry-after");
  const retryAfterSeconds = retryAfterHeader
    ? Number.parseInt(retryAfterHeader, 10)
    : undefined;

  return new ApiError(messageForStatus(response.status, parsed?.detail), response.status, {
    code: parsed?.code,
    retryAfterSeconds: Number.isFinite(retryAfterSeconds) ? retryAfterSeconds : undefined,
  });
}

interface RequestOptions {
  method?: "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
  body?: unknown;
  query?: Record<string, QueryValue>;
  signal?: AbortSignal;
}

/**
 * Semua panggilan backend melewati sini supaya cookie sesi, header, dan
 * pemetaan error konsisten di semua halaman.
 */
export async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { method = "GET", body, query, signal } = options;

  const isFormData = typeof FormData !== "undefined" && body instanceof FormData;

  let response: Response;
  try {
    response = await fetch(buildUrl(path, query), {
      method,
      // Cookie sesi access gate (FR-0.2) ikut terkirim.
      credentials: "include",
      headers: isFormData || body === undefined ? undefined : { "content-type": "application/json" },
      body: body === undefined ? undefined : isFormData ? body : JSON.stringify(body),
      signal,
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") throw error;
    throw new ApiError("Tidak dapat terhubung ke layanan. Periksa koneksi Anda.", 0);
  }

  if (!response.ok) throw await readError(response);
  if (response.status === 204) return undefined as T;

  return (await response.json()) as T;
}

export type { RequestOptions };
