import { NextResponse, type NextRequest } from "next/server";

const SESSION_COOKIE = "ida_gate";

/** Halaman yang boleh dibuka tanpa passcode. `/` exact saja, bukan prefix. */
const PUBLIC_EXACT = ["/", "/login"];

/**
 * Mode demo publik: gate dilewati, semua halaman terbuka.
 *
 * Diaktifkan lewat `NEXT_PUBLIC_OPEN_MODE=1` (backend juga butuh
 * `AUTH_OPEN_MODE=1`). Tujuannya presentasi ke user tanpa passcode, bukan
 * menghapus logika keamanan: backend tetap menerbitkan dan memeriksa sesi,
 * dan mematikan env ini mengembalikan gate seperti semula.
 */
const OPEN_MODE = process.env.NEXT_PUBLIC_OPEN_MODE === "1";

/**
 * Access gate di sisi server. Redirect terjadi sebelum
 * render, jadi isi /chat tidak pernah sampai ke browser tanpa sesi.
 *
 * Catatan: proxy hanya memeriksa keberadaan cookie. Penegakan sesungguhnya
 * (verifikasi passcode, kedaluwarsa, rate limit) ada di server action
 * `submitPasscode` dan di backend FastAPI. Cookie ini token akses demo,
 * bukan kredensial yang layak dicuri dan dipakai ulang.
 */
export function proxy(request: NextRequest) {
  const { pathname } = request.nextUrl;
  const hasSession = request.cookies.has(SESSION_COOKIE);

  if (OPEN_MODE) {
    // Semua halaman terbuka. /login tetap diarahkan ke /chat supaya CTA
    // landing (`/login?next=/chat`) mendarat langsung di aplikasi.
    if (pathname === "/login") {
      return NextResponse.redirect(new URL("/chat", request.url));
    }
    return NextResponse.next();
  }

  if (PUBLIC_EXACT.some((path) => pathname === path || pathname.startsWith(`${path}/`))) {
    // Sudah punya sesi, tidak perlu melihat form login lagi.
    if (pathname === "/login" && hasSession) {
      return NextResponse.redirect(new URL("/chat", request.url));
    }
    return NextResponse.next();
  }

  if (!hasSession) {
    const loginUrl = new URL("/login", request.url);
    if (pathname !== "/") loginUrl.searchParams.set("next", pathname);
    return NextResponse.redirect(loginUrl);
  }

  return NextResponse.next();
}

export const config = {
  matcher: [
    /*
     * Route halaman saja. `/api/*` **wajib dikecualikan**.
     *
     * Middleware berjalan sebelum rewrite, jadi kalau `/api/v1/*` ikut
     * dicakup, request API akan kena redirect ke halaman login dan
     * membalas HTML. Akibatnya `fetch` di browser gagal parse JSON dan
     * cookie `ida_session` tidak pernah sampai, persis bug yang membuat
     * login ditolak, padahal backend-nya sehat.
     *
     * API tidak butuh gate frontend: backend punya `/api/v1/auth/verify`
     * dan `require_session`-nya sendiri, yang memeriksa `ida_session`.
     * Dua lapis gate untuk hal yang sama justru hanya menambah tempat gagal.
     */
    "/((?!api/|_next/static|_next/image|favicon.ico|icon.svg|.*\\.png$|.*\\.svg$|robots.txt).*)",
  ],
};
