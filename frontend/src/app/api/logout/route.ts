import { cookies, headers } from "next/headers";
import { redirect } from "next/navigation";
import { SESSION_COOKIE } from "@/lib/auth/session";
import { API_BASE_URL, isMockMode } from "@/lib/api/config";
import { resolveRequestOrigin } from "@/lib/api/origin";

/**
 * Menghapus cookie sesi access gate lalu kembali ke layar login.
 *
 * `GET` diperlakukan sama seperti `POST`: pemanggil dari browser memakai
 * `fetch(..., {keepalive: true})` saat sesi backend terlanjur habis, dan
 * pemanggilan itu harus bisa membersihkan cookie tanpa navigasi form.
 */
export async function GET() {
  return logout();
}

export async function POST() {
  return logout();
}

async function logout() {
  const jar = await cookies();

  // Cabut sesi di backend juga, bukan cuma di browser. Cookie penanda
  // (`ida_gate`) saja tidak membatalkan token server; token `ida_session`
  // tetap valid sampai TTL kalau hanya cookie-nya yang dihapus.
  const sessionToken = jar.get("ida_session")?.value;
  if (!isMockMode && sessionToken) {
    try {
      const origin = resolveRequestOrigin(await headers());
      await fetch(`${origin}${API_BASE_URL}/api/v1/auth/logout`, {
        method: "POST",
        headers: { cookie: `ida_session=${sessionToken}` },
        cache: "no-store",
      });
    } catch {
      // Backend mati tetap lanjut logout di sisi klien.
    }
  }

  jar.delete(SESSION_COOKIE);
  jar.delete("ida_session");
  redirect("/login");
}