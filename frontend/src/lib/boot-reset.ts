import { getHealth } from "@/lib/api";
import { isMockMode } from "@/lib/api/config";

/**
 * Deteksi backend yang dijalankan ulang, lalu bersihkan state browser.
 *
 * Sesi akses dan riwayat percakapan hidup di memori proses backend. Setelah
 * restart, keduanya sudah tidak ada, tapi browser masih memegang cookie
 * `ida_gate`, sehingga pengguna bisa masuk seolah tidak terjadi apa-apa dan
 * menemukan riwayat yang tidak bisa dibuka. Gejalanya membingungkan: "kok
 * masih login, tapi datanya kosong".
 *
 * Backend menandai setiap proses dengan `boot_id` yang berubah tiap start.
 * Nilai itu disimpan di localStorage; begitu berbeda, penanda sesi di browser
 * dibuang dan pengguna diminta masuk ulang. Dengan begitu restart benar-benar
 * berarti mulai bersih.
 */

const BOOT_KEY = "ida_boot_id";

/** Jalankan sekali saat aplikasi dibuka di browser. */
export async function resetStaleBrowserState(): Promise<void> {
  // Mode fixture tidak punya backend, jadi tidak ada proses yang bisa
  // di-restart. Membersihkan di sini hanya akan menghapus state pengguna
  // tanpa alasan.
  if (isMockMode) return;

  let health;
  try {
    health = await getHealth();
  } catch {
    // Backend belum hidup. Jangan buang apa pun, kalau backendnya memang
    // sedang mati, menghapus sesi hanya memaksa login yang akan gagal juga.
    return;
  }

  const bootId = health.fallback?.boot_id;
  if (!bootId) return;

  let previous: string | null = null;
  try {
    previous = window.localStorage.getItem(BOOT_KEY);
  } catch {
    // localStorage bisa diblokir (mode privasi ketat). Tanpa penyimpanan,
    // deteksi restart tidak mungkin; lanjutkan tanpa membersihkan.
    return;
  }

  if (previous === null) {
    // Kunjungan pertama di browser ini: catat, tidak ada yang perlu dibuang.
    try {
      window.localStorage.setItem(BOOT_KEY, bootId);
    } catch {
      // Diabaikan: kegagalan menyimpan tidak boleh menggagalkan aplikasi.
    }
    return;
  }

  if (previous === bootId) return;

  // Backend baru saja dijalankan ulang.
  try {
    window.localStorage.setItem(BOOT_KEY, bootId);
  } catch {
    // Diabaikan.
  }

  // Cabut sesi di backend dan hapus cookie penanda, lalu paksa login ulang.
  // Dilakukan lewat route logout supaya token lama benar-benar dicabut, bukan
  // hanya dihapus di sisi browser.
  try {
    await fetch("/api/logout", { method: "POST", keepalive: true });
  } catch {
    // Backend tidak bisa dihubungi; cookie tetap akan dibersihkan server
    // saat halaman login dimuat.
  }

  const next = `${window.location.pathname}${window.location.search}`;
  // Hard navigation disengaja: seluruh state React dan cache query harus
  // dibuang, karena semuanya milik proses backend yang sudah mati.
  // eslint-disable-next-line @next/next/no-location-assign-relative-destination -- intentionally a hard navigation
  window.location.assign(`/login?next=${encodeURIComponent(next)}`);
}