/**
 * Salin worker PDF.js ke `public/` sebelum `dev` dan `build`.
 *
 * Worker dimuat oleh browser lewat URL statis, jadi berkasnya harus ada di
 * `public/`. Menyalin di awal lebih pasti daripada mengandalkan resolusi
 * bundler, yang berbeda antara webpack dan Turbopack di Next.js.
 *
 * Berkas hasil salin tidak di-commit (lihat `.gitignore`).
 */

import { copyFile, mkdir, stat } from "node:fs/promises";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const scriptDir = dirname(fileURLToPath(import.meta.url));
const projectDir = join(scriptDir, "..");
const source = join(projectDir, "node_modules", "pdfjs-dist", "build", "pdf.worker.min.mjs");
const publicDir = join(projectDir, "public");
const target = join(publicDir, "pdf.worker.min.mjs");

async function main() {
  try {
    await stat(source);
  } catch {
    console.error(
      `Berkas worker PDF.js tidak ditemukan di ${source}. Jalankan npm install lebih dulu.`,
    );
    process.exitCode = 1;
    return;
  }

  await mkdir(publicDir, { recursive: true });
  await copyFile(source, target);

  const { size } = await stat(target);
  console.log(`pdf.worker.min.mjs disalin ke public/ (${Math.round(size / 1024)} KB).`);
}

main().catch((error) => {
  const message = error instanceof Error ? error.message : String(error);
  console.error(`Gagal menyalin worker PDF.js: ${message}`);
  process.exitCode = 1;
});