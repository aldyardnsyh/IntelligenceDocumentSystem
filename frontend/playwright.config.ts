import { defineConfig, devices } from "@playwright/test";

/**
 * Uji browser untuk alur yang hanya bisa dinilai lewat interaksi nyata:
 * login, unggah berkas, streaming jawaban, klik sitasi, dan alih sesi.
 *
 * Server harus sudah hidup sebelum test dijalankan:
 *   backend  : uvicorn app.main:app --port 8000
 *   frontend : npm run dev
 *
 * `webServer` sengaja TIDAK dipakai di sini. Menjalankan server otomatis
 * membuat test sulit dibedakan dari proses manual, dan test yang_start sendiri
 * bercampur dengan log server yang sedang dibaca.
 */
export default defineConfig({
  testDir: "./e2e",
  timeout: 60_000,
  expect: { timeout: 15_000 },
  // Sengaja berurutan, satu worker. Banyak test mengunggah berkas yang sama
  // (groundedness dan preview-toast paling sering), dan `waitForDocumentReady`
  // mencocokkan baris tabel lewat nama berkas. Kalau dua test berjalan
  // bersamaan, nama itu muncul di dua baris dan pencocokannya gagal secara
  // acak. Karena itu waktu tambahan di CI diterima lewat batas waktu job,
  // bukan lewat paralel.
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: [["list"]],
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://localhost:3000",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    actionTimeout: 15_000,
  },
  projects: [
    { name: "chromium", use: { ...devices["Desktop Chrome"] } },
  ],
});