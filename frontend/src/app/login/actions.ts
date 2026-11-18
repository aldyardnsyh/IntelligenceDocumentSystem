"use server";

import { cookies, headers } from "next/headers";
import { redirect } from "next/navigation";
import { API_BASE_URL } from "@/lib/api/config";
import { resolveRequestOrigin, safeNextPath } from "@/lib/api/origin";
import { SESSION_COOKIE, SESSION_TTL_SECONDS } from "@/lib/auth/session";

export interface LoginState {
  status: "idle" | "error" | "rate_limited";
  message?: string;
  retryAfterSeconds?: number;
}

/**
 * Verifikasi passcode punya tepat satu sumber kebenaran:
 * POST /api/v1/auth/verify yang memutuskan. Rate limit dan session token
 * juga milik backend.
 */
async function checkPasscode(passcode: string): Promise<{
  ok: boolean;
  rateLimited: boolean;
  retryAfterSeconds?: number;
  setCookies: string[];
}> {
  // URL harus absolut. `fetch` di server action berjalan di runtime Node,
    // dan keandalan URL relatif di sana bergantung pada versi Next.js.
    // Mengandalkan itu di jalur auth terlalu berisiko: kalau gagal, gejalanya
    // "login selalu gagal" tanpa pesan yang jelas.
    //
    // Host diambil dari header request, jadi permintaannya kembali ke origin
    // yang sama dengan tempat frontend disajikan. Di belakang reverse proxy
    // seperti Caddy, `x-forwarded-host` adalah host publik, bukan nama
    // container, mengambil dari sana membuat hasilnya benar baik di
    // localhost maupun di produksi.
    const origin = resolveRequestOrigin(await headers());

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
        setCookies: [] as string[],
      };
    }

    if (response.ok) {
      return {
        ok: true as const,
        rateLimited: false as const,
        setCookies: response.headers.getSetCookie(),
      };
    }
    return { ok: false as const, rateLimited: false as const, setCookies: [] as string[] };
}

/**
 * Menyetel cookie gerbang "sudah lewat halaman login" yang dibaca `proxy.ts`.
 *
 * Dipakai dua jalur masuk sekaligus: verifikasi passcode dan masuk demo. Satu
 * implementasi saja, karena dua salinan cookie yang berbeda atributnya adalah
 * cara paling mudah membuat salah satu jalur diam-diam tidak berfungsi.
 *
 * Cookie ini hanya penanda gerbang, bukan kredensial; passcode tetap
 * ditegakkan backend.
 *
 * `secure` mengikuti skema request, BUKAN `NODE_ENV`. Versi sebelumnya memakai
 * `NODE_ENV === "production"`, dan itu membuat login tidak pernah bertahan saat
 * aplikasi produksi diakses lewat HTTP (localhost untuk memeriksa hasil build,
 * IP LAN, atau CI): browser membuang cookie `Secure` yang dikirim lewat HTTP,
 * proxy tidak melihat sesi, dan setiap perpindahan halaman memantul ke /login
 * tanpa pesan apa pun.
 */
async function setGateCookie(origin: string): Promise<void> {
  const jar = await cookies();
  jar.set(SESSION_COOKIE, "1", {
    httpOnly: true,
    sameSite: "lax",
    secure: origin.startsWith("https://"),
    path: "/",
    maxAge: SESSION_TTL_SECONDS,
  });
}

export async function submitPasscode(
  _prev: LoginState,
  formData: FormData,
): Promise<LoginState> {
  const passcode = String(formData.get("passcode") ?? "").trim();

  // Backend mati, DNS salah, atau origin salah bukan "passcode salah".
  // Tanpa try/catch di sini, error-nya dilempar keluar dari server action
  // dan pengguna melihat halaman 500 generik, bukan pesan yang bisa ditindaklanjuti.
  let result: Awaited<ReturnType<typeof checkPasscode>>;
  try {
    result = await checkPasscode(passcode);
  } catch {
    return {
      status: "error",
      message: "Layanan autentikasi tidak dapat dihubungi. Coba lagi sebentar.",
    };
  }

  if (result.rateLimited) {
    return {
      status: "rate_limited",
      message: "Terlalu banyak percobaan gagal.",
      retryAfterSeconds: result.retryAfterSeconds,
    };
  }

  if (!result.ok) {
    return {
      status: "error",
      message: "Passcode salah. Periksa kembali atau hubungi penyedia demo.",
    };
  }

  // Skema request menentukan apakah cookie harus `Secure`.
  const origin = resolveRequestOrigin(await headers());

  const jar = await cookies();

  await setGateCookie(origin);

  // Cookie sesi backend (`ida_session`) harus ikut ke browser. Server action
  // ini berjalan di server, jadi `Set-Cookie` dari respons backend tidak
  // otomatis diteruskan, tanpa baris ini browser tidak pernah punya
  // sesi dan semua request API berikutnya kena 401.
  for (const raw of result.setCookies ?? []) {
    const [pair, ...attrParts] = raw.split(";");
    const eq = pair.indexOf("=");
    if (eq <= 0) continue;
    const name = pair.slice(0, eq).trim();
    const value = pair.slice(eq + 1).trim();
    let maxAge: number | undefined;
    let expires: Date | undefined;
    let path = "/";
    let httpOnly = true;
    let sameSite: "lax" | "strict" | "none" = "lax";
    // Bukan `NODE_ENV`. Backend sudah memutuskan berdasarkan skema request
    // lewat `_is_https_request`. Memaksa `Secure` di sini membuat cookie
    // dibuang browser saat aplikasi produksi diakses lewat HTTP, dan
    // gejalanya hanya "session_expired" pada setiap request berikutnya.
    let secure = origin.startsWith("https://");
    for (const attr of attrParts) {
      const [k, v] = attr.split("=").map((s) => s.trim());
      const key = k.toLowerCase();
      if (key === "max-age") maxAge = Number.parseInt(v ?? "", 10);
      else if (key === "expires" && v) expires = new Date(v);
      else if (key === "path" && v) path = v;
      else if (key === "httponly") httpOnly = true;
      else if (key === "samesite") {
        const sv = (v ?? "").toLowerCase();
        if (sv === "strict" || sv === "none" || sv === "lax") sameSite = sv;
      } else if (key === "secure") secure = true;
    }
    jar.set(name, value, {
      httpOnly,
      sameSite,
      secure,
      path,
      // `expires` ikut diteruskan supaya TTL yang ditentukan backend tetap
      // berlaku di browser, apa pun yang dikirimi.
      ...(expires ? { expires } : maxAge ? { maxAge } : {}),
    });
  }

  redirect(safeNextPath(String(formData.get("next") ?? "")) || "/chat");
}
