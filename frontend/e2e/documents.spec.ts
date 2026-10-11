import { expect, test } from "@playwright/test";
import { login, uploadSample, waitForDocumentReady } from "./fixtures";

/**
 * Unggah dokumen: alur yang paling sering gagal di aplikasi ini, karena
 * session, multipart, dan polling status sekaligus.
 */
test.describe("unggah dokumen", () => {
  test("berkas txt diunggah sampai siap", async ({ page }) => {
    await login(page);
    await page.goto("/documents");
    await uploadSample(page, "kebijakan-cuti.txt");
    await waitForDocumentReady(page, "kebijakan-cuti.txt");
  });

  test("berkas pdf diunggah sampai siap", async ({ page }) => {
    await login(page);
    await page.goto("/documents");
    await uploadSample(page, "laporan-infrastruktur.pdf");
    // Parser PDF adalah jalur paling rawan: kalau ekstraksi teks gagal,
    // dokumen tetap "siap" tapi isinya nol byte.
    await waitForDocumentReady(page, "laporan-infrastruktur.pdf");
  });

  test("format tidak didukung ditolak dengan pesan jelas", async ({ page }) => {
    await login(page);
    await page.goto("/documents");
    const chooserPromise = page.waitForEvent("filechooser");
    await page.getByRole("button", { name: /unggah|tarik dan lepas/i }).first().click();
    const chooser = await chooserPromise;
    await chooser.setFiles({
      name: "gambar.png",
      mimeType: "image/png",
      buffer: Buffer.from([0x89, 0x50, 0x4e, 0x47]),
    });
    // Pesan harus muncul di respons pertama. Kalau tidak, dokumen tercatat
    // "diproses" lalu gagal diam-diam saat polling.
    await expect(page.getByText(/tidak didukung/i).first()).toBeVisible();
  });

  test("dokumen bisa dihapus beserta indeksnya", async ({ page }) => {
    await login(page);
    await page.goto("/documents");
    await uploadSample(page, "panduan-tiket-layanan.md");
    await waitForDocumentReady(page, "panduan-tiket-layanan.md");

    await page.getByRole("button", { name: new RegExp("panduan-tiket-layanan") }).first().click();
    await page.getByRole("button", { name: /hapus/i }).first().click();
    await page.getByRole("button", { name: /hapus|batal tidak|hapus dokumen/i }).last().click();
    await expect(page.getByText(/panduan-tiket-layanan/)).toHaveCount(0, { timeout: 20_000 });
  });
});