import type { NextConfig } from "next";

/**
 * URL backend FastAPI. Hanya dibaca di server (build + rewrite), jadi tidak
 * memakai prefix `NEXT_PUBLIC_`: alamat backend tidak perlu masuk ke bundle
 * browser.
 *
 * **Default-nya bukan string kosong.** Nilai kosong membuat rewrite dimatikan
 * sepenuhnya saat build, karena `rewrites()` dievaluasi sekali di build time
 * lalu hasilnya dibekukan di `routes-manifest.json`. Gejalanya halus sekali:
 * aplikasi tetap jalan, tapi setiap request `/api/v1/*` jatuh ke halaman Next
 * sehingga login mengembalikan HTML alih-alih JSON.
 *
 * Karena itu nilai defaultnya `http://api:8000` (nama service di compose).
 * Mode fixture di-browser dikendalikan `NEXT_PUBLIC_USE_BACKEND`, bukan
 * lewat nilai kosong di sini.
 */
const BACKEND_ORIGIN = process.env.BACKEND_ORIGIN ?? "http://api:8000";

/**
 * Sakelar profil, dibaca dengan aturan yang sama seperti `readFlag` di
 * `src/lib/api/config.ts` supaya rewrite dan UI tidak pernah berbeda pendapat.
 */
const useBackend = /^(1|true|yes|on)$/i.test(
  process.env.NEXT_PUBLIC_USE_BACKEND?.trim() ?? "",
);

const nextConfig: NextConfig = {
  /**
   * Build mandiri, tanpa `node_modules` di image runtime.
   *
   * Tanpa ini, image frontend ikut membawa seluruh dependency Next.js
   * (~400 MB). Dengan `standalone`, Next cuma menyalin modul yang benar-benar
   * dipakai, biasanya image turun ke ~150 MB.
   *
   * Di Vercel nilainya dibiarkan `undefined`: platform itu sudah punya bentuk
   * output sendiri dan `standalone` hanya memunculkan peringatan.
   */
  output: process.env.VERCEL ? undefined : "standalone",

  /**
   * Prefix `/api/v1` diproxy ke FastAPI.
   *
   * Ini bukan detail kosmetik; ini yang membuat alur login berfungsi.
   * Endpoint login mengembalikan `Set-Cookie: ida_session`. Kalau browser
   * memanggil backend dari origin berbeda, cookie itu milik origin backend,
   * sedangkan server action Next berjalan di origin frontend dan tidak punya
   * cookie jar, sehingga `Set-Cookie` dari backend dibuang dan tidak pernah
   * sampai ke browser.
   *
   * Dengan rewrite, browser hanya mengenal satu origin. Login, API, dan
   * `Set-Cookie` mengalir lewat origin frontend, lalu Next meneruskannya ke
   * backend. Cookie ikut naik-turun bersama setiap permintaan, di localhost
   * maupun saat deploy dengan dua domain terpisah. CORS dan cookie
   * lintas-domain tidak lagi jadi syarat.
   *
   * `BACKEND_ORIGIN` dibaca saat build, jadi nilainya harus ada sebagai
   * build-argumen kalau nanti berubah. Compose sudah mengaturnya.
   */
  async rewrites() {
    // Profil demo (`NEXT_PUBLIC_USE_BACKEND` kosong): tidak ada backend yang
    // bisa dituju. Tanpa cabang ini, `/api/v1/*` di Vercel tetap diproxy ke
    // `http://api:8000` dan gagal, padahal harusnya jatuh ke fixture browser.
    if (!useBackend) return [];

    // Saat backend aktif, rewrite selalu menyala. Cabang "mati" di sini
    // sengaja tidak membaca nilai `BACKEND_ORIGIN` kosong; itulah penyebab
    // request `/api/v1/*` sampai ke halaman Next alih-alih backend. Sakelar
    // profil dibaca terpisah di atas.
    return [
      {
        source: "/api/v1/:path*",
        destination: `${BACKEND_ORIGIN}/api/v1/:path*`,
      },
    ];
  },
};

export default nextConfig;
