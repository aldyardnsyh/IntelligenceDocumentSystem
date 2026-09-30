/**
 * Konfigurasi runtime API.
 *
 * - `NEXT_PUBLIC_API_BASE_URL` diisi  -> talking ke FastAPI sungguhan.
 * - kosong                             -> memakai fixture retrieval in-browser
 *                                        (src/lib/mock) supaya UI tetap bisa
 *                                        diklik tanpa backend.
 *
 * Fixture tidak pernah berpura-pura jadi backend: setiap halaman yang
 * bergantung padanya menampilkan banner "Mode demo".
 *
 * ## Dua env var, bukan satu
 *
 * `NEXT_PUBLIC_USE_BACKEND` adalah sakelarnya: `1` berarti memakai FastAPI,
 * kosong berarti fixture lokal.
 *
 * `NEXT_PUBLIC_API_BASE_URL` hanya override untuk kasus khusus, dan sengaja
 * kosong di konfigurasi normal supaya request memakai path relatif
 * `/api/v1/...` yang diproxy oleh rewrite di `next.config.ts`. Bagi browser
 * semua request — termasuk `Set-Cookie` dari endpoint login — lalu berada di
 * satu origin, dan cookie ikut naik-turun bersama setiap permintaan.
 *
 * Mengisi URL absolut membuat browser bicara langsung ke backend. Di localhost
 * itu masih jalan karena cookie berbagi domain, tapi `Set-Cookie` dari endpoint
 * login tetap hilang: pemanggilnya server action Next yang berjalan di origin
 * frontend, dan di sana tidak ada cookie jar. Di deploy dengan dua domain
 * terpisah, cookie lintas-domain juga butuh `SameSite=None; Secure` yang rapuh.
 */

function readFlag(value: string | undefined): boolean {
  return /^(1|true|yes|on)$/i.test(value?.trim() ?? "");
}

/** True kalau UI harus bicara dengan FastAPI, bukan fixture lokal. */
export const isMockMode = !readFlag(process.env.NEXT_PUBLIC_USE_BACKEND);

/**
 * Prefix untuk semua request API. String kosong berarti path relatif, yang
 * diteruskan rewrite Next.js ke backend.
 */
export const API_BASE_URL = isMockMode
  ? ""
  : (process.env.NEXT_PUBLIC_API_BASE_URL ?? "").replace(/\/+$/, "");

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
