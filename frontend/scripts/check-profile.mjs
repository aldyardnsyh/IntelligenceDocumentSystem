/**
 * Periksa env sebelum `next build`.
 *
 * Mode demo (fixture in-browser) sudah dihapus: frontend selalu berbicara
 * dengan backend FastAPI. Env yang tersisa hanya menentukan DI MANA backend
 * itu berada (rewrite build-time `BACKEND_ORIGIN` atau override
 * `NEXT_PUBLIC_API_BASE_URL`), jadi profil tunggal: backend.
 *
 * Pemeriksaan ini sengaja dijalankan di `prebuild` supaya kesalahan konfigurasi
 * gagal keras saat build, bukan diam-diam menampilkan halaman yang tidak bisa
 * menjawab apa pun di produksi.
 */

function main() {
  if (process.env.NEXT_PUBLIC_USE_BACKEND) {
    console.error(
      "NEXT_PUBLIC_USE_BACKEND sudah tidak dipakai (mode demo dihapus); "
        + "hapus variabel ini dari environment build.",
    );
    process.exitCode = 1;
    return;
  }
  if (process.env.NEXT_PUBLIC_DEMO_ENTRY) {
    console.error(
      "NEXT_PUBLIC_DEMO_ENTRY sudah tidak dipakai (mode demo dihapus); "
        + "hapus variabel ini dari environment build.",
    );
    process.exitCode = 1;
    return;
  }
  console.log("Profil terdeteksi: backend.");
}

main();
