/**
 * Access gate.
 *
 * Passcode dibandingkan di backend (`ACCESS_PASSCODE_SHA256` di
 * `backend/.env`); frontend tidak pernah menyimpan atau memverifikasi
 * passcode. Form mengirim ke server action, server action meneruskan ke
 * backend, dan cookie HTTP-only dibangun dari respons backend.
 */

export const SESSION_COOKIE = "ida_gate";
/** default 24 jam. */
export const SESSION_TTL_SECONDS = 60 * 60 * 24;

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
  return process.env.NEXT_PUBLIC_DEV_PASSCODE_HINT?.trim() || null;
}
