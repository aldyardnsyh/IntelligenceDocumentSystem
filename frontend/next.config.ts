import type { NextConfig } from "next";

/**
 * URL backend FastAPI. Hanya dibaca di server (build + rewrite), jadi tidak
 * memakai prefix `NEXT_PUBLIC_`: alamat backend tidak perlu masuk ke bundle
 * browser.
 *
 * Kosong berarti tidak ada rewrite dan `NEXT_PUBLIC_API_BASE_URL` kosong
 * membuat frontend berjalan dengan fixture lokal.
 */
const BACKEND_ORIGIN = process.env.BACKEND_ORIGIN ?? "http://localhost:8000";

const nextConfig: NextConfig = {
  /**
   * Prefix `/api/v1` diproxy ke FastAPI.
   *
   * Ini bukan Detail kosmetik; ini yang membuat alur login berfungsi.
   * Endpoint login mengembalikan `Set-Cookie: ida_session`. Kalau browser
   * memanggil backend secara langsung dari origin berbeda, cookie itu
   * management milik origin backend, sedangkan server action Next berjalan di
   * origin frontend dan tidak punya cookie jar -- sehingga `Set-Cookie` dari
   * backend dibuang dan tidak pernah sampai ke browser.
   *
   * Dengan rewrite, browser hanya mengenal satu origin. Login, API, dan
   * `Set-Cookie` mengalir lewat origin frontend, lalu Next meneruskannya ke
   * backend. Cookie ikut naik-turun bersama setiap permintaan, di localhost
   * maupun di domain terpisah saat deploy. CORS dan cookie lintas-domain
   * tidak lagi jadi syarat.
   */
  async rewrites() {
    if (!process.env.BACKEND_ORIGIN) return [];
    return [
      {
        source: "/api/v1/:path*",
        destination: `${BACKEND_ORIGIN}/api/v1/:path*`,
      },
    ];
  },
};

export default nextConfig;
