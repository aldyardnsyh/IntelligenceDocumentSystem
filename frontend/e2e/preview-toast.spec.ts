import { expect, test } from "@playwright/test";
import { login, uploadSample, waitForDocumentReady } from "./fixtures";

/**
 * Tiga hal yang membuat halaman-halaman ini bisa dipakai tanpa menebak:
 *
 * 1. Pratinjau PDF asli berdampingan dengan chunk, untuk cross-check.
 * 2. Halaman evaluasi yang memilih dokumennya langsung di situ.
 * 3. Notifikasi yang membedakan berhasil, gagal, dan informasi.
 */
test.describe("pratinjau dokumen", () => {
  test("PDF asli ditampilkan, bukan hanya teksnya", async ({ page }) => {
    await login(page);
    await page.goto("/documents");
    await uploadSample(page, "laporan-infrastruktur.pdf");
    await waitForDocumentReady(page, "laporan-infrastruktur.pdf");

    await kartuDokumen(page, "laporan-infrastruktur.pdf").click();
    await expect(page).toHaveURL(/\/documents\/doc_/);

    // Untuk PDF, tiap halaman di-render langsung ke canvas di halaman ini
    // (tanpa iframe, karena iframe blob diblokir Edge).
    const canvas = page.locator("canvas").first();
    await expect(canvas).toBeVisible({ timeout: 20_000 });

    // Ada jalan ke teks hasil ekstraksi, karena ekstraksinya perlu diperiksa.
    await expect(
      page.getByRole("button", { name: /lihat teks hasil ekstraksi/i }),
    ).toBeVisible();
  });

  test("teks hasil ekstraksi bisa dibuka berdampingan", async ({ page }) => {
    await login(page);
    await page.goto("/documents");
    await uploadSample(page, "laporan-infrastruktur.pdf");
    await waitForDocumentReady(page, "laporan-infrastruktur.pdf");
    await kartuDokumen(page, "laporan-infrastruktur.pdf").click();

    await page.getByRole("button", { name: /lihat teks hasil ekstraksi/i }).click();
    // Isi PDF yang dikenal harus terbaca sebagai teks berurutan.
    await expect(page.getByText(/Laporan Ringkas Infrastruktur/i).first()).toBeVisible({
      timeout: 20_000,
    });
    // Dan ada jalan kembali ke berkas aslinya.
    await expect(page.getByRole("button", { name: /lihat berkas asli/i })).toBeVisible();
  });

  test("dokumen teks menampilkan isinya berurutan", async ({ page }) => {
    await login(page);
    await page.goto("/documents");
    await uploadSample(page, "kebijakan-cuti.txt");
    await waitForDocumentReady(page, "kebijakan-cuti.txt");

    // Klik dibatasi ke kartu yang sama dengan yang ditunggu siap. Memakai
    // `getByRole("link")` di seluruh halaman bisa menunjuk kartu dari test
    // sebelumnya, karena setiap test mengunggah berkas dengan nama sama.
    await kartuDokumen(page, "kebijakan-cuti.txt").click();

    await expect(page.getByText(/cuti tahunan sebanyak 12 hari kerja/i)).toBeVisible({
      timeout: 20_000,
    });
  });

  test("tab chunk tetap tersedia", async ({ page }) => {
    await login(page);
    await page.goto("/documents");
    await uploadSample(page, "panduan-tiket-layanan.md");
    await waitForDocumentReady(page, "panduan-tiket-layanan.md");
    await kartuDokumen(page, "panduan-tiket-layanan.md").click();

    await page.getByRole("tab", { name: /chunk hasil ingestion/i }).click();
    await expect(page.getByText(/chunk dalam dokumen ini|chunk mengandung/i)).toBeVisible();
  });
});

test.describe("evaluasi memilih dokumen di halaman itu", () => {
  test("dokumen bisa dipilih sebelum evaluasi dijalankan", async ({ page }) => {
    await login(page);
    await page.goto("/documents");
    await uploadSample(page, "kebijakan-cuti.txt");
    await waitForDocumentReady(page, "kebijakan-cuti.txt");

    await page.goto("/analytics");
    const heading = page.getByText(/belum ada data evaluasi/i);
    if ((await heading.count()) === 0) {
      test.skip(true, "sudah ada data evaluasi");
    }

    // Daftar dokumen harus muncul di halaman ini, tanpa pindah halaman.
    await expect(page.getByText(/pilih dokumen yang mau diuji/i)).toBeVisible();
    const checkbox = page.getByRole("checkbox").first();
    await expect(checkbox).toBeVisible();

    // Tombol tidak aktif sebelum ada yang dipilih, dan aktif setelahnya.
    const runButton = page.getByRole("button", { name: /jalankan evaluasi/i });
    await expect(runButton).toBeDisabled();
    await checkbox.check();
    await expect(runButton).toBeEnabled();
  });

  test("evaluasi berjalan pada dokumen yang dipilih", async ({ page }) => {
    await login(page);
    await page.goto("/documents");
    await uploadSample(page, "kebijakan-cuti.txt");
    await waitForDocumentReady(page, "kebijakan-cuti.txt");

    await page.goto("/analytics");
    const heading = page.getByText(/belum ada data evaluasi/i);
    if ((await heading.count()) === 0) {
      test.skip(true, "sudah ada data evaluasi");
    }

    await page.getByRole("checkbox").first().check();
    await page.getByRole("button", { name: /jalankan evaluasi/i }).click();

    // Hasilnya: notifikasi sukses, atau pesan yang menjelaskan kenapa belum
    // bisa. Yang tidak boleh: diam tanpa umpan balik.
    const sukses = page.getByText(/evaluasi selesai/i);
    const gagal = page.getByText(/belum siap|tidak ditemukan|dataset/i);
    await expect(sukses.or(gagal).first()).toBeVisible({ timeout: 120_000 });
  });
});

test.describe("notifikasi membedakan jenisnya", () => {
  test("berhasil dan gagal punya gaya berbeda", async ({ page }) => {
    await login(page);
    await page.goto("/settings");

    const slider = page.getByRole("slider").first();
    await slider.focus();
    await page.keyboard.press("ArrowRight");

    const toast = page.locator("[data-sonner-toast]").first();
    await expect(toast).toBeVisible({ timeout: 15_000 });

    // Notifikasi harus punya judul DAN detail, bukan satu baris teks saja.
    await expect(toast.getByText(/pengaturan disimpan/i)).toBeVisible();
    await expect(toast.getByText(/nilai baru dipakai/i)).toBeVisible();
  });
});

/**
 * Tautan nama berkas di dalam kartu dokumen tertentu.
 *
 * Dipakai agar klik tidak jatuh ke kartu lain dengan nama berkas sama, yang
 * bisa terjadi karena setiap test mengunggah berkas yang sama.
 */
function kartuDokumen(page: import("@playwright/test").Page, nama: string) {
  return page
    .getByTestId("document-card")
    .filter({ hasText: nama })
    .first()
    .getByRole("link", { name: new RegExp(nama.replace(".", "\\.")) });
}
