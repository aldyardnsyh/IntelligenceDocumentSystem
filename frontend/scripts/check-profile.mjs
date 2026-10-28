/**
 * Periksa kombinasi env profil sebelum `next build`.
 *
 * Kombinasi env yang salah tidak menghasilkan error saat build: aplikasi tetap
 * terkompilasi, lalu berperilaku salah di produksi (misalnya pintu masuk demo
 * terbuka padahal backend aktif). Karena itu pemeriksaan ini sengaja gagal
 * keras di `prebuild`, bukan sekadar memberi peringatan.
 *
 * Aturan yang diperiksa:
 * 1. `NEXT_PUBLIC_USE_BACKEND` dan `NEXT_PUBLIC_DEMO_ENTRY` tidak boleh sama-sama aktif.
 * 2. `NEXT_PUBLIC_DEMO_ENTRY` aktif tanpa backend wajib punya `DEMO_PASSCODE`.
 * 3. `DEMO_PASSCODE` harus hash heksadesimal 16 karakter (FNV-1a) atau 64
 *    karakter (SHA-256); passcode mentah akan selalu gagal diverifikasi.
 *
 * Nilai `DEMO_PASSCODE` tidak pernah dicetak, termasuk saat gagal.
 */

const HEX_16 = /^[0-9a-f]{16}$/i;
const HEX_64 = /^[0-9a-f]{64}$/i;

function readFlag(value) {
  return /^(1|true|yes|on)$/i.test(value?.trim() ?? "");
}

/** Cetak alasan gagal lalu set exit code. Tidak memanggil process.exit(). */
function fail(message) {
  console.error(message);
  process.exitCode = 1;
}

function main() {
  const useBackend = readFlag(process.env.NEXT_PUBLIC_USE_BACKEND);
  const demoEntry = readFlag(process.env.NEXT_PUBLIC_DEMO_ENTRY);
  const passcode = (process.env.DEMO_PASSCODE ?? "").trim();

  if (useBackend && demoEntry) {
    fail("Kombinasi tidak sah: tombol masuk demo tidak boleh aktif saat backend aktif.");
    return;
  }

  if (demoEntry && !useBackend && passcode.length === 0) {
    fail("DEMO_PASSCODE wajib diisi saat masuk demo diaktifkan.");
    return;
  }

  if (passcode.length > 0 && !HEX_16.test(passcode) && !HEX_64.test(passcode)) {
    fail(
      "DEMO_PASSCODE harus hash heksadesimal: 16 karakter (FNV-1a) atau 64 karakter "
        + "(SHA-256). Passcode mentah tidak akan pernah cocok saat verifikasi.",
    );
    return;
  }

  // Urutan penting: backend lebih dulu, karena profil demo hanya ada saat
  // backend mati.
  const profile = useBackend ? "backend" : demoEntry ? "demo" : "lokal";
  console.log(`Profil terdeteksi: ${profile}.`);
}

main();