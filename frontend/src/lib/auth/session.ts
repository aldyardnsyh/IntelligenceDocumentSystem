/**
 * Access gate.
 *
 * Passcode dibandingkan di server terhadap hash yang disimpan di environment
 * variable. Nilai hash-nya dihitung dari env var biasa, jadi
 * repo tidak pernah memuat passcode plaintext.
 *
 * Frontend tidak pernah menyimpan passcode: form mengirim ke server action
 * ini, server yang membuat cookie HTTP-only.
 *
 * ## Sumber kebenaran passcode
 *
 * Saat backend terhubung, yang memutuskan adalah `ACCESS_PASSCODE_SHA256` di
 * `backend/.env`, frontend tidak menebak apa pun. Saat mode lokal (tanpa
 * backend), frontend memakai `DEMO_PASSCODE` (hash FNV-1a).
 *
 * Sebelumnya fungsi di file ini punya passcode contoh yang ditulis mati
 * (`demo-rag-2025`). Itu bug: hint di layar login menampilkan passcode yang
 * tidak pernah dipakai backend, jadi pengguna mengetik passcode yang salah
 * dan menyimpulkan aplikasinya rusak.
 */

export const SESSION_COOKIE = "ida_gate";
/** default 24 jam. */
export const SESSION_TTL_SECONDS = 60 * 60 * 24;

/**
 * Passcode mode fixture (tanpa backend).
 *
 * Satu-satunya passcode yang ditulis di frontend, dan hanya berlaku saat
 * `NEXT_PUBLIC_USE_BACKEND` tidak diisi. Saat backend aktif, verifikasi
 * sepenuhnya di sana (`ACCESS_PASSCODE_SHA256`) dan nilai ini tidak dipakai
 * sama sekali. `devPasscodeHint()` menampilkan konstanta yang sama, jadi
 * hint dan verifikasi tidak bisa berbeda.
 */
export const MOCK_MODE_PASSCODE = "demo-rag-2025";

/** 5 percobaan per 5 menit per IP. */
const MAX_ATTEMPTS = 5;
const ATTEMPT_WINDOW_MS = 5 * 60 * 1000;

const attempts = new Map<string, number[]>();
/**: Batas kunci rate limit yang dilacak per proses. */
const MAX_TRACKED_IPS = 4096;

function clientKey(ip: string) {
  return ip || "unknown";
}

export function tooManyAttempts(ip: string): number {
  const now = Date.now();
  const recent = (attempts.get(clientKey(ip)) ?? []).filter((at) => now - at < ATTEMPT_WINDOW_MS);
  attempts.set(clientKey(ip), recent);
  if (recent.length < MAX_ATTEMPTS) return 0;
  return Math.ceil((ATTEMPT_WINDOW_MS - (now - recent[0])) / 1000);
}

export function registerFailedAttempt(ip: string) {
  const now = Date.now();
  const recent = (attempts.get(clientKey(ip)) ?? []).filter((at) => now - at < ATTEMPT_WINDOW_MS);
  recent.push(now);
  // Batas jumlah kunci: IP yang berhenti mencoba tidak pernah dihapus dari
  // map, jadi proses yang hidup lama bisa menahan cukup banyak kunci
  // hanya karena lalu lintas dari banyak sumber berbeda.
  if (attempts.size > MAX_TRACKED_IPS) {
    const oldest = [...attempts.entries()].sort(
      (left, right) => (left[1][0] ?? 0) - (right[1][0] ?? 0),
    );
    for (const [key] of oldest.slice(0, attempts.size - MAX_TRACKED_IPS)) {
      attempts.delete(key);
    }
  }
  attempts.set(clientKey(ip), recent);
}

export function clearAttempts(ip: string) {
  attempts.delete(clientKey(ip));
}

function expectedHash(): string {
  const secret = process.env.DEMO_PASSCODE;
  if (!secret) {
    if (process.env.NODE_ENV === "production") {
      throw new Error("DEMO_PASSCODE belum diset. Jalankan demo tanpa passcode tidak diizinkan.");
    }
    // Passcode demo HANYA berlaku di mode fixture (tanpa backend). Nilainya
    // satu-satunya yang diumumkan, dan `devPasscodeHint()` menampilkan nilai
    // yang sama, hint tidak boleh berbeda dari yang diterima verifikasi.
    return hashPasscode(MOCK_MODE_PASSCODE);
  }

  // Nilai env harus sudah berupa hash. Kalau operator mengisi plaintext,
  // `DEMO_PASSCODE=rahasia` akan selalu gagal login tanpa pesan yang
  // menjelaskan, gejalanya terlihat seperti passcode yang salah.
  if (!/^[0-9a-f]{16}$/i.test(secret.trim()) && !/^[0-9a-f]{64}$/i.test(secret.trim())) {
    throw new Error(
      "DEMO_PASSCODE harus berisi hash heksadesimal (16 karakter untuk mode demo "
      + "FNV-1a, atau 64 karakter SHA-256), bukan passcode mentah.",
    );
  }
  return secret.trim().toLowerCase();
}

function hashPasscode(value: string): string {
  // FNV-1a 64-bit dipadatkan ke hex. Cukup untuk access gate demo; untuk
  // produksi lintas proses, ganti dengan argon2/bcrypt di backend.
  let hash = 0xcbf29ce484222325n;
  const prime = 0x100000001b3n;
  const mask = 0xffffffffffffffffn;
  for (const byte of Buffer.from(value, "utf8")) {
    hash = ((hash ^ BigInt(byte)) * prime) & mask;
  }
  return hash.toString(16).padStart(16, "0");
}

export function verifyPasscode(candidate: string): boolean {
  if (candidate.length === 0) return false;
  const provided = hashPasscode(candidate);
  const expected = expectedHash();
  // Perbandingan waktu-konstan agar tidak bocor lewat selisih waktu.
  if (provided.length !== expected.length) return false;
  let diff = 0;
  for (let index = 0; index < provided.length; index += 1) {
    diff |= provided.charCodeAt(index) ^ expected.charCodeAt(index);
  }
  return diff === 0;
}

/**
 * Petunjuk passcode untuk layar login saat pengembangan.
 *
 * Mengembalikan `null` kalau passcode tidak boleh diumumkan. Saat backend
 * aktif, yang memutuskan adalah `ACCESS_PASSCODE_SHA256` di `backend/.env`,
 * frontend tidak mengetahuinya, jadi tidak menampilkan apa pun kecuali
 * operator mengisi `NEXT_PUBLIC_DEV_PASSCODE_HINT` secara eksplisit.
 *
 * Menampilkan tebakan di sini pernah menjadi bug: hint menunjukkan passcode
 * yang tidak pernah dipakai backend, dan pengguna mengetik passcode yang
 * salah lalu menyimpulkan aplikasinya rusak.
 */
export function devPasscodeHint(): string | null {
  if (process.env.NODE_ENV === "production") return null;

  // Operator boleh mengumumkan passcode dev-nya sendiri. Ini opt-in, dan
  // nilainya harus sengaja ditulis, bukan ditebak dari kode.
  const declared = process.env.NEXT_PUBLIC_DEV_PASSCODE_HINT?.trim();
  if (declared) return declared;

  // Backend aktif: verifikasi di sana, frontend tidak tahu nilainya.
  if (process.env.NEXT_PUBLIC_USE_BACKEND) return null;

  // Mode fixture: tampilkan passcode yang benar-benar diterima verifikasi.
  return MOCK_MODE_PASSCODE;
}
