import { expect, test } from "@playwright/test";
import { login, uploadSample, waitForDocumentReady } from "./fixtures";

/**
 * Dua perilaku produk yang menentukan apakah sistem ini berguna:
 *
 * 1. Saat tidak ada konteks dokumen, pengguna tetap mendapat jawaban, tapi
 *    jawaban itu WAJIB dilabeli "bukan dari dokumen Anda". Menyembunyikan
 *    labelnya membuat pengguna memakai informasi yang tidak bisa
 *    diverifikasi.
 * 2. Setiap dokumen bisa punya percakapan privat sendiri, dan percakapan itu
 *    hanya mencari di dalam dokumen itu.
 */
test.describe("pertanyaan tentang koleksi dokumen", () => {
  test("pertanyaan 'carikan dokumen' dijawab dari daftar nyata", async ({ page }) => {
    await login(page);
    await page.goto("/documents");
    await uploadSample(page, "kebijakan-cuti.txt");
    await waitForDocumentReady(page, "kebijakan-cuti.txt");
    await page.goto("/chat");

    const input = page.getByPlaceholder(/tanyakan sesuatu|tulis pertanyaan/i);
    await input.fill("carikan dokumen terkait dengan tiketing");
    await input.press("Enter");

    // Jawaban harus menyebut dokumen yang benar-benar ada, atau menjelaskan
    // bahwa tidak ada yang cocok. Yang tidak boleh: daftar buku dengan
    // penulis dan URL yang tidak bisa dicek.
    const jawaban = page.getByText(/dokumen yang tersedia|tidak ada dokumen yang cocok/i);
    await expect(jawaban.first()).toBeVisible({ timeout: 45_000 });

    // Penanda halusinasi referensi tidak boleh muncul.
    await expect(page.getByText(/https?:\/\//i)).toHaveCount(0);
    await expect(page.getByText(/\| judul \|/i)).toHaveCount(0);
  });

  test("daftar dokumen tersedia dijawab tanpa model", async ({ page }) => {
    await login(page);
    await page.goto("/documents");
    await uploadSample(page, "kebijakan-cuti.txt");
    await waitForDocumentReady(page, "kebijakan-cuti.txt");
    await page.goto("/chat");

    const input = page.getByPlaceholder(/tanyakan sesuatu|tulis pertanyaan/i);
    await input.fill("dokumen apa saja yang tersedia?");
    await input.press("Enter");

    // Nama berkas yang benar-benar diunggah harus muncul di jawaban.
    await expect(page.getByText(/kebijakan-cuti\.txt/).first()).toBeVisible({
      timeout: 45_000,
    });
  });
});

test.describe("jawaban tanpa dokumen", () => {
  test.beforeEach(async ({ page }) => {
    await login(page);
    await page.goto("/documents");
    await uploadSample(page, "kebijakan-cuti.txt");
    await waitForDocumentReady(page, "kebijakan-cuti.txt");
    await page.goto("/chat");
  });

  test("pertanyaan di luar dokumen tetap dijawab, dengan label jelas", async ({ page }) => {
    const input = page.getByPlaceholder(/tanyakan sesuatu|tulis pertanyaan/i);
    await input.fill("berapa harga tiket bioskop di jakarta?");
    await input.press("Enter");

    // Label harus muncul. Ini pembeda antara "model menjawab" dan
    // "model mengarang dengan percaya diri".
    await expect(page.getByText(/bukan dari dokumen anda/i).first()).toBeVisible({
      timeout: 45_000,
    });
    // Dan jawabannya bukan pesan "tidak ditemukan".
    await expect(page.getByText(/tidak ditemukan dalam dokumen/i)).toHaveCount(0);
  });

  test("sakelar dimatikan mengembalikan mode ketat", async ({ page }) => {
    await page.getByLabel(/jawab tanpa dokumen/i).uncheck();
    const input = page.getByPlaceholder(/tanyakan sesuatu|tulis pertanyaan/i);
    await input.fill("berapa harga tiket bioskop di jakarta?");
    await input.press("Enter");
    await expect(page.getByText(/tidak ditemukan dalam dokumen/i).first()).toBeVisible({
      timeout: 45_000,
    });
  });
});

test.describe("chat privat per dokumen", () => {
  test("tombol dari halaman dokumen membuka chat ber-scope", async ({ page }) => {
    await login(page);
    await page.goto("/documents");
    await uploadSample(page, "panduan-tiket-layanan.md");
    await waitForDocumentReady(page, "panduan-tiket-layanan.md");

    await page.getByRole("link", { name: /tanya dokumen ini/i }).first().click();
    await expect(page).toHaveURL(/\/chat\?doc=doc_/);
    // Badge scope harus terlihat: pengguna perlu tahu pencarian dibatasi.
    await expect(page.getByText(/panduan-tiket-layanan\.md/).first()).toBeVisible();
  });

  test("badge scope membedakan dua mode dengan jelas", async ({ page }) => {
    await login(page);
    // Mode global: badge "Semua dokumen".
    await page.goto("/chat");
    await expect(page.getByText(/semua dokumen/i).first()).toBeVisible();

    // Mode dokumen: badge menampilkan nama berkas.
    await page.goto("/documents");
    await uploadSample(page, "kebijakan-cuti.txt");
    await waitForDocumentReady(page, "kebijakan-cuti.txt");
    await page.getByRole("link", { name: /tanya dokumen ini/i }).first().click();

    await expect(page.getByText(/kebijakan-cuti\.txt/).first()).toBeVisible();
    await expect(page.getByText(/^semua dokumen$/i)).toHaveCount(0);
  });

  test("sesi ber-scope tidak mencari di dokumen lain", async ({ page }) => {
    await login(page);

    // Dua dokumen dengan topik berbeda.
    await page.goto("/documents");
    await uploadSample(page, "kebijakan-cuti.txt");
    await waitForDocumentReady(page, "kebijakan-cuti.txt");
    await uploadSample(page, "panduan-tiket-layanan.md");
    await waitForDocumentReady(page, "panduan-tiket-layanan.md");

    // Buka chat khusus dokumen tiket, lalu tanya hal yang hanya ada di
    // dokumen cuti. Jawabannya tidak boleh menemukan sumber dari dokumen cuti.
    const card = page
      .locator("li, article, div")
      .filter({ hasText: "panduan-tiket-layanan.md" })
      .first();
    await card.getByRole("link", { name: /tanya dokumen ini/i }).click();
    await expect(page).toHaveURL(/\/chat\?doc=doc_/);

    const input = page.getByPlaceholder(/tanyakan sesuatu|tulis pertanyaan/i);
    await input.fill("berapa hari cuti tahunan karyawan?");
    await input.press("Enter");
    await expect(page.getByText(/tidak ditemukan|bukan dari dokumen/i).first()).toBeVisible({
      timeout: 45_000,
    });
    // Tidak boleh ada sitasi dari dokumen cuti.
    await expect(page.getByText(/kebijakan-cuti\.txt/).first()).toBeHidden({ timeout: 5_000 });
  });

  test("pertanyaan dijawab dengan sitasi dokumen itu, dan tercatat di sidebar", async ({ page }) => {
    await login(page);
    await page.goto("/documents");
    await uploadSample(page, "panduan-tiket-layanan.md");
    await waitForDocumentReady(page, "panduan-tiket-layanan.md");
    await page.getByRole("link", { name: /tanya dokumen ini/i }).first().click();

    const input = page.getByPlaceholder(/tanyakan sesuatu|tulis pertanyaan/i);
    await input.fill("berapa jam SLA respons tiket prioritas tinggi?");
    await input.press("Enter");

    // Jawaban bersumber dokumen: sitasi harus muncul.
    await expect(page.getByRole("link", { name: /chunk|hal\./i }).first()).toBeVisible({
      timeout: 45_000,
    });

    // Sesi masuk daftar, dikelompokkan di bawah nama dokumennya.
    await expect(page.getByText(/panduan-tiket-layanan\.md/).first()).toBeVisible();
  });
});