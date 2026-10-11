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

/**
 * Endpoint auth tidak boleh memicu redirect 401 di atas: login yang gagal
 * akan memantul balik ke /login dan seterusnya.
 */
function isAuthEndpoint(path: string) {
  return path.includes("/auth/verify") || path.includes("/auth/logout");
}

/**
 * Cookie `ida_gate` hanya penanda melewati gerbang. Cookie ini HTTP-only
 * dan tidak bisa dihapus dari JavaScript, jadi kedaluwarsanya dikembalikan
 * lewat route server yang stubborn response-nya tidak dihiraukan.
 */
function expireGateCookie() {
  void fetch("/api/logout", { method: "POST", keepalive: true }).catch(() => {});
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

  if (!response.ok) {
    const error = await readError(response);

    // 401 di tengah pemakaian: cookie penanda gerbang masih ada (TTL 24 jam)
    // padahal sesi backend sudah tidak berlaku. Tanpa penanganan di sini,
    // setiap layar menunjukkan error yang sama dan satu-satunya jalan keluar
    // adalah tombol logout yang tidak selalu terlihat.
    //
    // Request login sendiri dikecualikan supaya gagalnya login tidak memicu
    // loop redirect.
    if (error.status === 401 && !isAuthEndpoint(path)) {
      expireGateCookie();
      const next = `${window.location.pathname}${window.location.search}`;
      // Muat ulang penuh, bukan navigasi client-side: cookie gate harus
      // ikut hilang sebelum halaman login dirender, dan `router.push` tidak
      // membersihkan cache React Router.
      // eslint-disable-next-line @next/next/no-location-assign-relative-destination -- intentionally a hard navigation
      window.location.assign(`/login?next=${encodeURIComponent(next)}`);
    }

    throw error;
  }
  if (response.status === 204) return undefined as T;

  return (await response.json()) as T;
}

export type { RequestOptions };
