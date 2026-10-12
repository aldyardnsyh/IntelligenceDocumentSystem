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
 * path internal.
 *
 * Pendekatan lama hanya memeriksa tiga hal: diawali `/`, tidak diawali `//`,
 * dan tidak diawali `/\`. Itu tidak cukup. Karakter kontrol lolos ke sana,
 * dan beberapa di antaranya membuat browser membaca ulang nilai itu sebagai
 * URL absolut: `"/\n/evil.example"` diawali `/` dan bukan `//`, jadi lolos,
 * lalu diartikan sebagai `//evil.example` oleh parser URL. Selain itu
 * `/%5Cevil.example` dan `/\tevil.example` juga lolos padahal jelas bukan
 * path yang pernah dibuat aplikasi ini.
 *
 * Validasi sekarang memakai daftar karakter yang diizinkan, bukan daftar
 * yang ditolak. Path di aplikasi ini hanya berisi huruf, angka, `-`, `_`,
 * `.`, `~`, `/`, `?`, `=`, `&`, dan `%`. Apa pun di luar itu ditolak, jadi
 * tidak ada karakter kontrol, backslash, spasi, atau tanda pagar yang bisa
 * menyusup.
 *
 * `%` tetap diizinkan karena path nyata bisa memuatnya, tapi hanya dalam
 * bentuk escape heksadesimal yang sah (`%2F`, `%20`). Escape yang tidak sah
 * ditolak. Escape yang sah pun masih diperiksa lagi setelah didekode: `%5C`
 * adalah backslash dan `%0d%0a` adalah CRLF, keduanya hanya bentuk lain dari
 * karakter yang sudah ditolak di atas. Router Next.js men-dekode path sebelum
 * mencocokkannya, jadi nilai ter-encode tidak boleh dianggap aman.
 */
const SAFE_NEXT_PATH = /^\/(?:[A-Za-z0-9\-._~!$&'()*+,;=:@/?]|%[0-9A-Fa-f]{2})*$/;

/** Karakter yang tetap terlarang setelah escape didekode. */
const FORBIDDEN_AFTER_DECODE = /[\\\u0000-\u001f\u007f]/;

/**
 * Decode sampai hasilnya tidak berubah lagi.
 *
 * Satu kali decode tidak cukup. `%255C` adalah backslash yang di-encode dua
 * kali: sekali decode menghasilkan `%5C`, yang masih terlihat seperti teks
 * biasa, dan baru decode kedua menghasilkan `\`. Selama nilainya masih
 * berubah setelah decode, ada lapisan encoding yang belum dibuka.
 */
function fullyDecode(raw: string): string | null {
  let current = raw;
  // Batas 5 putaran cukup untuk setiap kasus nyata; lapisan encoding yang
  // lebih dalam dari itu berarti nilainya dibuat untuk menyembunyikan
  // sesuatu, dan itu ditolak saja.
  for (let round = 0; round < 5; round += 1) {
    let next: string;
    try {
      next = decodeURIComponent(current);
    } catch {
      // Escape yang tidak bisa didekode berarti nilainya cacat, bukan path.
      return null;
    }
    if (next === current) return current;
    current = next;
  }
  return null;
}

export function safeNextPath(raw: string | undefined | null): string {
  if (!raw) return "";
  if (raw.length > 512) return "";
  // `//` adalah bentuk protokol-relatif. Ini keluar dari origin ini kalau
  // diteruskan, dan tidak pernah dipakai di aplikasi ini.
  if (raw.startsWith("//")) return "";
  if (!SAFE_NEXT_PATH.test(raw)) return "";

  const decoded = fullyDecode(raw);
  if (decoded === null) return "";
  if (FORBIDDEN_AFTER_DECODE.test(decoded)) return "";
  if (decoded.startsWith("//")) return "";

  // Lapis terakhir: buktikan hasilnya benar-benar tetap di origin ini.
  // Pemeriksaan di atas sudah menutup semua kasus yang diketahui, tapi
  // resolusi URL adalah penentu sesungguhnya bagaimana browser membaca nilai
  // ini. Kalau hasilnya keluar dari origin, tolak, apa pun alasannya.
  try {
    const resolved = new URL(raw, "https://internal.invalid");
    if (resolved.origin !== "https://internal.invalid") return "";
    return resolved.pathname + resolved.search;
  } catch {
    return "";
  }
}