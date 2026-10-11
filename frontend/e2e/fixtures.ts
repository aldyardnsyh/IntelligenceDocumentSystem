import { expect, test, type Page } from "@playwright/test";

/**
 * Fixture bersama untuk seluruh spec.
 *
 * Passcode diambil dari `E2E_PASSCODE` karena nilainya tidak boleh ditulis
 * mati di test: passcode demo yang sama di semua clone membuat verifikasi ini
 * tidak berarti apa-apa.
 */
export const PASSCODE = process.env.E2E_PASSCODE ?? "uji-e2e";

/** Masuk lewat UI, bukan lewat API, supaya alur session ikut teruji. */
export async function login(page: Page, passcode = PASSCODE) {
  await page.goto("/chat");
  await page.getByLabel("Passcode akses").fill(passcode);
  await page.getByRole("button", { name: "Masuk" }).click();
  await expect(page).toHaveURL(/\/chat/);
}

/** Unggah berkas dari folder `backend/samples`. */
export async function uploadSample(page: Page, filename: string) {
  const chooser = page.waitForEvent("filechooser");
  await page.getByRole("button", { name: /unggah|tarik dan lepas/i }).first().click();
  const fileChooser = await chooser;
  await fileChooser.setFiles(`../backend/samples/${filename}`);
}

/** Tunggu dokumen selesai diindeks. */
export async function waitForDocumentReady(page: Page, filename: string) {
  const row = page.getByRole("row").filter({ hasText: filename });
  await expect(row).toContainText(/siap|ready/i, { timeout: 120_000 });
}

test.beforeEach(async ({ page }) => {
  // Setiap test mulai dari keadaan tanpa sesi, supaya test tidak saling
  // bergantung pada cookie yang tertinggal.
  await page.context().clearCookies();
});