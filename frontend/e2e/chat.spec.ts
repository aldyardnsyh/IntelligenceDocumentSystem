import { expect, test } from "@playwright/test";
import { login, uploadSample, waitForDocumentReady } from "./fixtures";

/**
 * Chat: dua aturan yang menentukan apakah sistem ini bisa dipercaya.
 *
 * 1. Pertanyaan yang jawabannya ada di dokumen harus dijawab **dengan sitasi**.
 * 2. Pertanyaan yang tidak ada jawabannya harus ditolak dengan "tidak
 *    ditemukan", bukan dijawab mengarang.
 *
 * Yang diuji di sini persis dua aturan itu, plus sesi yang harus bertahan
 * setelah pertanyaan pertama.
 */
test.describe("tanya jawab", () => {
  test.beforeEach(async ({ page }) => {
    await login(page);
    await page.goto("/documents");
    await uploadSample(page, "panduan-tiket-layanan.md");
    await waitForDocumentReady(page, "panduan-tiket-layanan.md");
    await page.goto("/chat");
  });

  test("pertanyaan yang ada jawabannya memberi sitasi", async ({ page }) => {
    const input = page.getByPlaceholder(/apa yang ingin ditanyakan|tulis pertanyaan/i);
    await input.fill("berapa hari SLA respons tiket prioritas sedang?");
    await input.press("Enter");

    // Jawaban pertama harus benar-benar muncul. Dulu ini yang hilang:
    // halaman dipromosikan ke /chat/<id> saat stream berjalan, komponen
    // dilepas, dan stream dibatalkan.
    const answer = page.locator('[data-role="assistant"], .whitespace-pre-wrap').last();
    await expect(answer).not.toBeEmpty({ timeout: 30_000 });
    await expect(page.getByRole("link", { name: /chunk|hal\.|halaman/i }).first())
      .toBeVisible({ timeout: 15_000 });
  });

  test("pertanyaan di luar dokumen dijawab tidak ditemukan", async ({ page }) => {
    const input = page.getByPlaceholder(/apa yang ingin ditanyakan|tulis pertanyaan/i);
    await input.fill("berapa harga tiket bioskop di jakarta?");
    await input.press("Enter");
    // Gate anti-halusinasi. Kalau sistem mengarang di sini, seluruh
    // janji "tidak akan mengarang" jadi tidak berarti apa-apa.
    await expect(page.getByText(/tidak ditemukan dalam dokumen/i).first())
      .toBeVisible({ timeout: 30_000 });
  });

  test("sesi bertahan setelah pertanyaan pertama", async ({ page }) => {
    const input = page.getByPlaceholder(/apa yang ingin ditanyakan|tulis pertanyaan/i);
    await input.fill("apa itu prioritas tiket?");
    await input.press("Enter");
    await expect(page).toHaveURL(/\/chat\/ses_/, { timeout: 30_000 });

    await input.fill("dan kapan tiket ditutup otomatis?");
    await input.press("Enter");
    // Riwayat harus menumpuk di sesi yang sama, bukan sesi baru.
    await expect(page.locator("text=/dan kapan tiket ditutup otomatis/i")).toBeVisible({
      timeout: 30_000,
    });
  });

  test("klik sitasi membuka chunk sumbernya", async ({ page }) => {
    const input = page.getByPlaceholder(/apa yang ingin ditanyakan|tulis pertanyaan/i);
    await input.fill("berapa hari SLA respons tiket prioritas sedang?");
    await input.press("Enter");

    const citation = page.getByRole("link", { name: /chunk|hal\.|halaman/i }).first();
    await expect(citation).toBeVisible({ timeout: 30_000 });
    await citation.click();

    await expect(page).toHaveURL(/\/documents\/doc_.*chunk=/);
    // Chunk tujuan harus benar-benar terlihat, bukan hanya URL-nya benar.
    await expect(page.getByText(/dari sitasi/i)).toBeVisible({ timeout: 15_000 });
  });

  test("percakapan baru tidak menampilkan layar error", async ({ page }) => {
    const input = page.getByPlaceholder(/apa yang ingin ditanyakan|tulis pertanyaan/i);
    await input.fill("apa itu prioritas tiket?");
    await input.press("Enter");
    await expect(page).toHaveURL(/\/chat\/ses_/, { timeout: 30_000 });

    await page.getByRole("button", { name: /percakapan baru/i }).first().click();
    await expect(page).toHaveURL(/\/chat$/);
    // Id sesi lokal yang belum pernah dibuat di server pernah dipromosikan,
    // dan hasilnya 404 "sesi tidak ditemukan".
    await expect(page.getByText(/sesi tidak ditemukan|sudah berakhir/i)).toHaveCount(0);
  });
});