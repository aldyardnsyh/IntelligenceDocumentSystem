/**
 * Konfigurasi runtime API.
 *
 * Frontend selalu berbicara dengan FastAPI. Tidak ada mode demo: fixture
 * in-browser sudah dihapus, karena UI tiruan yang tampil ke pengunjung lebih
 * merusak kepercayaan daripada pesan error yang jujur.
 *
 * ## Kenapa dua env var
 *
 * `NEXT_PUBLIC_API_BASE_URL` sengaja kosong di konfigurasi normal supaya
 * request memakai path relatif `/api/v1/...` yang diproxy oleh rewrite di
 * `next.config.ts` (nilai build-time `BACKEND_ORIGIN`). Bagi browser semua
 * request, termasuk `Set-Cookie` dari endpoint login, berada di satu origin.
 *
 * Mengisi URL absolut membuat browser bicara langsung ke backend. Di localhost
 * itu masih jalan karena cookie berbagi domain, tapi `Set-Cookie` dari endpoint
 * login tetap hilang: pemanggilnya server action Next yang berjalan di origin
 * frontend, dan di sana tidak ada cookie jar. Di deploy dengan dua domain
 * terpisah, cookie lintas-domain juga butuh `SameSite=None; Secure` yang rapuh.
 */

/**
 * Prefix untuk semua request API. String kosong berarti path relatif, yang
 * diteruskan rewrite Next.js ke backend.
 */
export const API_BASE_URL = (process.env.NEXT_PUBLIC_API_BASE_URL ?? "").replace(
  /\/+$/,
  "",
);

/**
 * Tautan keluar. Kosong berarti tombolnya sengaja nonaktif dengan label
 * "belum diatur", bukan tautan ke halaman yang tidak ada.
 */
function normalizeUrl(raw: string | undefined): string | null {
  const value = raw?.trim();
  if (!value) return null;
  // Hanya http/https yang boleh, supaya env var yang salah isi tidak
  // menghasilkan skema skrip berbahaya.
  try {
    const url = new URL(value);
    return url.protocol === "http:" || url.protocol === "https:" ? url.toString() : null;
  } catch {
    return null;
  }
}

export const externalLinks = {
  repository: normalizeUrl(process.env.NEXT_PUBLIC_REPO_URL),
  apiDocs: normalizeUrl(process.env.NEXT_PUBLIC_API_DOCS_URL),
  tracing: normalizeUrl(process.env.NEXT_PUBLIC_LANGFUSE_URL),
} as const;
