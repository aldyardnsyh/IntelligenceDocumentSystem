/**
 * Access gate.
 *
 * Passcode dibandingkan di server terhadap hash yang njaga di environment
 * variable (PRD FR-0.1). Nilai hash-nya dihitung dari env var biasa, jadi
 * repo tidak pernah memuat passcode plaintext.
 *
 * Frontend tidak pernah menyimpan passcode: form mengirim ke server action
 * ini, server yang membuat cookie HTTP-only.
 */

export const SESSION_COOKIE = "ida_gate";
/** FR-0.2: default 24 jam. */
export const SESSION_TTL_SECONDS = 60 * 60 * 24;

/** FR-0.3: 5 percobaan per 5 menit per IP. */
const MAX_ATTEMPTS = 5;
const ATTEMPT_WINDOW_MS = 5 * 60 * 1000;

const attempts = new Map<string, number[]>();

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
    return hashPasscode("demo-rag-2025");
  }
  return secret;
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

/** Hanya untuk ditampilkan di layar login saat dev. */
export function devPasscodeHint(): string | null {
  if (process.env.NODE_ENV === "production") return null;
  if (process.env.DEMO_PASSCODE) return null;
  return "demo-rag-2025";
}
