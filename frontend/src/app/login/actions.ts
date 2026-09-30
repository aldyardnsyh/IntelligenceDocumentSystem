"use server";

import { cookies, headers } from "next/headers";
import { redirect } from "next/navigation";
import { API_BASE_URL, isMockMode } from "@/lib/api/config";
import {
  SESSION_COOKIE,
  SESSION_TTL_SECONDS,
  clearAttempts,
  registerFailedAttempt,
  tooManyAttempts,
  verifyPasscode,
} from "@/lib/auth/session";

export interface LoginState {
  status: "idle" | "error" | "rate_limited";
  message?: string;
  retryAfterSeconds?: number;
}

/**
 * Verifikasi passcode punya tepat satu sumber kebenaran.
 *
 * - Backend terhubung  : POST /api/v1/auth/verify yang memutuskan. Rate limit
 *   dan session token juga milik backend (FR-0.2, FR-0.3).
 * - Mode lokal         : passcode dicocokkan dengan hash dari env var
 *   DEMO_PASSCODE, supaya UI tetap bisa dicoba tanpa backend.
 */
async function checkPasscode(passcode: string) {
  if (!isMockMode) {
    // URL harus absolut. `fetch` di server action berjalan di runtime Node,
    // dan keandalan URL relatif di sana bergantung pada versi Next.js.
    // Mengandalkan itu di jalur auth terlalu berisiko: kalau gagal, gejalanya
    // "login selalu gagal" tanpa pesan yang jelas.
    //
    // Host diambil dari header request, jadi permintaannya kembali ke origin
    // yang sama dengan tempat frontend disajikan. Di belakang reverse proxy
    // seperti Caddy, `x-forwarded-host` adalah host publik, bukan nama
    // container -- mengambil dari sana membuat hasilnya benar baik di
    // localhost maupun di produksi.
    const headersList = await headers();
    const host = headersList.get("x-forwarded-host") ?? headersList.get("host");
    const proto = headersList.get("x-forwarded-proto") ?? (host?.includes("localhost") ? "http" : "https");
    const origin = host ? `${proto}://${host}` : "http://localhost:3000";

    const response = await fetch(`${origin}${API_BASE_URL}/api/v1/auth/verify`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ passcode }),
      // `Set-Cookie` dari endpoint login harus sampai ke browser. Cache
      // Next.js bisa menahan respons ini, sehingga login kedua mengembalikan
      // respons lama tanpa header cookie dan sesi tidak pernah terbentuk.
      cache: "no-store",
    });

    if (response.status === 429) {
      const retryAfter = Number.parseInt(response.headers.get("retry-after") ?? "", 10);
      return {
        ok: false as const,
        rateLimited: true as const,
        retryAfterSeconds: Number.isFinite(retryAfter) ? retryAfter : 60,
      };
    }

    if (response.ok) return { ok: true as const, rateLimited: false as const };
    return { ok: false as const, rateLimited: false as const };
  }

  return {
    ok: verifyPasscode(passcode),
    rateLimited: false as const,
  };
}

export async function submitPasscode(
  _prev: LoginState,
  formData: FormData,
): Promise<LoginState> {
  const passcode = String(formData.get("passcode") ?? "").trim();

  // Rate limit lokal hanya berlaku di mode lokal. Saat backend aktif,
  // reload per IP dijalankan di sana supaya berlaku lintas instance.
  const ip =
    (await headers()).get("x-forwarded-for")?.split(",")[0]?.trim()
    ?? "local";

  if (isMockMode) {
    const waitSeconds = tooManyAttempts(ip);
    if (waitSeconds > 0) {
      return {
        status: "rate_limited",
        message: "Terlalu banyak percobaan gagal.",
        retryAfterSeconds: waitSeconds,
      };
    }
  }

  const result = await checkPasscode(passcode);

  if (result.rateLimited) {
    return {
      status: "rate_limited",
      message: "Terlalu banyak percobaan gagal.",
      retryAfterSeconds: result.retryAfterSeconds,
    };
  }

  if (!result.ok) {
    if (isMockMode) registerFailedAttempt(ip);
    return {
      status: "error",
      message: "Passcode salah. Periksa kembali atau hubungi penyedia demo.",
    };
  }

  if (isMockMode) clearAttempts(ip);

  // Cookie ini hanya penanda "sudah lewat gerbang" untuk proxy.ts, bukan
  // kredensial. Penegakan sesungguhnya ada di backend.
  (await cookies()).set(SESSION_COOKIE, "1", {
    httpOnly: true,
    sameSite: "lax",
    secure: process.env.NODE_ENV === "production",
    path: "/",
    maxAge: SESSION_TTL_SECONDS,
  });

  redirect("/chat");
}
