import { NextResponse, type NextRequest } from "next/server";

const SESSION_COOKIE = "ida_gate";

/** Halaman yang boleh dibuka tanpa passcode. */
const PUBLIC_PATHS = ["/login"];

/**
 * Access gate di sisi server (PRD FR-0.1, TC-13). Redirect terjadi sebelum
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

  if (PUBLIC_PATHS.some((path) => pathname === path || pathname.startsWith(`${path}/`))) {
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
     * Semua route kecuali aset statis dan file internal Next.
     */
    "/((?!_next/static|_next/image|favicon.ico|icon.svg|.*\\.png$|.*\\.svg$|robots.txt).*)",
  ],
};
