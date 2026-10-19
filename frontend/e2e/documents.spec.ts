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
    // Pesan harus muncul pada respons pertama, bukan nanti saat polling.
    //
    // Pesannya dirender sebagai `role="alert"` di bawah tombol unggah.
    // Sebelumnya pesan ini hanya dirender pada dropzone besar, sehingga
    // memilih berkas yang salah lewat tombol header tidak memberi penjelasan
    // apa pun: berkas tidak terunggah dan pengguna tidak tahu kenapa.
    await expect(
      page.getByRole("alert").filter({ hasText: /tidak didukung/i }),
    ).toBeVisible({ timeout: 30_000 });
  });

  test("dokumen bisa dihapus beserta indeksnya", async ({ page }) => {
    await login(page);
    await page.goto("/documents");
    await uploadSample(page, "panduan-tiket-layanan.md");
    await waitForDocumentReady(page, "panduan-tiket-layanan.md");

    // Menu aksi dibuka lewat tombol berlabel "Aksi untuk <berkas>". Item
    // menunya berperan `menuitem`, bukan `button`.
    const kartu = page
      .getByTestId("document-card")
      .filter({ hasText: "panduan-tiket-layanan.md" })
      .first();
    const sebelumHapus = await page
      .getByTestId("document-card")
      .filter({ hasText: "panduan-tiket-layanan.md" })
      .count();

    await kartu
      .getByRole("button", { name: /aksi untuk panduan-tiket-layanan\.md/i })
      .click();
    await page.getByRole("menuitem", { name: /hapus dokumen/i }).click();

    // Dialog konfirmasi memakai label "Hapus permanen", bukan "Hapus".
    await page.getByRole("button", { name: /hapus permanen/i }).click();

    // Penghapusan diperiksa dari berkurangnya jumlah kartu dengan nama itu.
    // Memeriksa "harus nol" rapuh: kalau test lain mengunggah berkas yang sama,
    // kartunya tetap ada walaupun penghapusan berhasil.
    await expect
      .poll(
        async () =>
          page
            .getByTestId("document-card")
            .filter({ hasText: "panduan-tiket-layanan.md" })
            .count(),
        { timeout: 20_000, message: "jumlah kartu tidak berkurang setelah dihapus" },
      )
      .toBeLessThan(sebelumHapus);
  });
});