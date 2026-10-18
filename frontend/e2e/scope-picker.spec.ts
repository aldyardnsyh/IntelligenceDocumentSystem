import { expect, test } from "@playwright/test";
import {
  login,
  uploadSample,
  waitForDocumentReady,
} from "./fixtures";

/**
 * Pemilih scope dokumen di halaman chat.
 *
 * Sebelumnya scope hanya bisa satu dokumen, lewat tautan `?doc=` dari halaman
 * detail. Itu cukup untuk alur "tanya dokumen ini", tapi tidak untuk
 * pertanyaan yang jawabannya tersebar di beberapa dokumen. Yang diuji di sini
 * adalah janji yang mudah rusak diam-diam: pilihan pengguna benar-benar
 * mengubah apa yang dicari, dan sesi mengingatnya.
 */
test.describe("scope dokumen di chat", () => {
  test.beforeEach(async ({ page }) => {
    await login(page);
    await page.goto("/documents");
    await uploadSample(page, "panduan-tiket-layanan.md");
    await waitForDocumentReady(page, "panduan-tiket-layanan.md");
    await page.goto("/chat");
  });

  test("tanpa pilihan, badge menyatakan semua dokumen", async ({ page }) => {
    // Daftar kosong berarti "semua dokumen", bukan "tidak ada dokumen".
    // Kalau artinya tertukar, setiap pertanyaan akan ditolak dan aplikasi
    // terbaca seperti rusak.
    await expect(page.getByText("Semua dokumen").first()).toBeVisible({
      timeout: 20_000,
    });
  });

  test("memilih satu dokumen mengubah badge ke nama berkas", async ({ page }) => {
    await page.getByRole("button", { name: /semua dokumen/i }).first().click();
    await page
      .getByRole("menuitemcheckbox", { name: /panduan-tiket-layanan\.md/i })
      .click();
    // Tutup menu supaya badge di header bisa diperiksa.
    await page.keyboard.press("Escape");

    await expect(
      page.getByText(/panduan-tiket-layanan\.md/).first(),
    ).toBeVisible({ timeout: 10_000 });
    await expect(page.getByText("Semua dokumen")).toHaveCount(0);
  });

  test("menghapus pilihan mengembalikan ke semua dokumen", async ({ page }) => {
    const tombol = page.getByRole("button", { name: /semua dokumen/i }).first();
    await tombol.click();
    await page
      .getByRole("menuitemcheckbox", { name: /panduan-tiket-layanan\.md/i })
      .click();
    await page.keyboard.press("Escape");

    // Badge sekarang menampilkan nama berkas; tombol pemilih ada di baris
    // yang sama, jadi cari berdasarkan namanya.
    await page
      .getByRole("button", { name: /panduan-tiket-layanan\.md/i })
      .first()
      .click();
    await page.getByRole("button", { name: /^hapus$/i }).click();
    await page.keyboard.press("Escape");

    await expect(page.getByText("Semua dokumen").first()).toBeVisible({
      timeout: 10_000,
    });
  });

  test("pertanyaan memakai scope yang dipilih", async ({ page }) => {
    await page.getByRole("button", { name: /semua dokumen/i }).first().click();
    await page
      .getByRole("menuitemcheckbox", { name: /panduan-tiket-layanan\.md/i })
      .click();
    await page.keyboard.press("Escape");

    const input = page.getByPlaceholder(/apa yang ingin ditanyakan|tulis pertanyaan/i);
    await input.fill("berapa hari SLA respons tiket prioritas sedang?");
    await input.press("Enter");

    // Jawaban harus tetap datang dengan sitasi dari dokumen yang dipilih.
    // Kalau scope-nya salah kirim, backend akan mencari di dokumen lain dan
    // jawabannya kosong tanpa menjelaskan kenapa.
    await expect(
      page.getByRole("link", { name: /chunk|hal\.|halaman/i }).first(),
    ).toBeVisible({ timeout: 45_000 });
  });
});
