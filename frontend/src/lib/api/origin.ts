/**
 * Origin kanonik untuk self-fetch dari server (server action dan route handler).
 *
 * Host diambil dari header request supaya permintaannya kembali ke origin yang
 * sama dengan tempat frontend disajikan. Dua hal yang harus benar:
 *
 * 1. Skema. Header proxy lebih dulu; tanpa itu, host non-`localhost`
 *    (`127.0.0.1`, IP LAN, nama container) dianggap HTTPS dan self-fetch gagal
 *    karena tidak ada TLS di sana.
 * 2. Host. Header `Host` dikendalikan pemanggil, jadi tidak dipakai sebagai
 *    nilai tepercaya kalau `APP_ORIGIN` sudah diset; header hanya cadangan.
 */
export function resolveRequestOrigin(headersList: Headers): string {
  const configured = process.env.APP_ORIGIN?.trim();
  if (configured) return configured.replace(/\/+$/, "");

  const host = headersList.get("x-forwarded-host") ?? headersList.get("host");
  if (!host) return "http://localhost:3000";

  const forwardedProto = headersList.get("x-forwarded-proto")?.split(",")[0]?.trim();
  const isLocalHost = host.includes("localhost") || host.includes("127.") || host.includes("[::1]");
  const proto = forwardedProto ?? (isLocalHost ? "http" : "https");
  return `${proto}://${host}`;
}

/**
 * `?next=` dari proxy dipakai untuk kembali ke halaman yang sedang dibuka
 * setelah login. Nilainya berasal dari URL, jadi harus divalidasi: hanya
 * path internal. `//evil.example` dan `https://evil.example` akan membuat
 * browser keluar dari origin ini kalau diteruskan mentah.
 */
export function safeNextPath(raw: string | undefined | null): string {
  if (!raw) return "";
  if (!raw.startsWith("/")) return "";
  if (raw.startsWith("//") || raw.startsWith("/\\")) return "";
  return raw;
}