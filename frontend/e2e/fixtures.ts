import { expect, test, type Page } from "@playwright/test";
import { AMBANG_E2E, PASSCODE } from "./env";

/**
 * Fixture bersama untuk seluruh spec.
 *
 * Passcode diambil dari `E2E_PASSCODE` karena nilainya tidak boleh ditulis
 * mati di test: passcode demo yang sama di semua clone membuat verifikasi ini
 * tidak berarti apa-apa.
 */
export { PASSCODE } from "./env";

/**
 * Placeholder kotak tanya di halaman chat.
 *
 * Didefinisikan sekali di sini karena versi sebelumnya ditulis ulang di setiap
 * spec dengan pola yang berbeda-beda, dan sebagian besar tidak cocok dengan
 * teks yang benar-benar dirender (`Tanyakan sesuatu tentang dokumen Anda`).
 * Gejalanya `waiting for getByPlaceholder(...)` lalu timeout, padahal
 * halamannya tampil normal.
 */
export const CHAT_INPUT_PLACEHOLDER = /tanyakan sesuatu tentang dokumen|tulis pertanyaan/i;

/** Kotak tanya, dipakai semua spec chat. */
export function chatInput(page: Page) {
  return page.getByPlaceholder(CHAT_INPUT_PLACEHOLDER);
}

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

/**
 * Tunggu dokumen selesai diindeks.
 *
 * Halaman dokumen merender kartu, bukan tabel. Versi sebelumnya mencari
 * `role="row"`, elemen yang tidak pernah ada di halaman ini, sehingga setiap
 * pemanggil menunggu 120 detik lalu gagal walaupun dokumennya sudah "Siap
 * ditanyai". Itu satu-satunya penyebab 30 kegagalan E2E sekaligus.
 *
 * Selector sekarang memakai `data-testid` dari kartu. Kalau ada lebih dari
 * satu kartu dengan nama berkas sama (test lain mengunggah berkas yang sama),
 * `.first()` dipakai: yang diperiksa adalah "ada dokumen siap dengan nama ini",
 * bukan "hanya ada satu".
 */
export async function waitForDocumentReady(page: Page, filename: string) {
  const card = page
    .getByTestId("document-card")
    .filter({ hasText: filename })
    .first();
  await expect(
    card,
    `kartu dokumen "${filename}" tidak muncul`,
  ).toBeVisible({ timeout: 120_000 });
  await expect(
    card,
    `dokumen "${filename}" tidak pernah mencapai status siap`,
  ).toContainText(/siap ditanyai|ready/i, { timeout: 120_000 });
}

test.beforeEach(async ({ baseURL, request }) => {
  // Setiap test dimulai dari keadaan yang sama, seperti di CI yang selalu
  // memakai database kosong.
  //
  // Dua hal yang dipulihkan:
  //
  // 1. Cookie sesi. `request` Playwright punya cookie jar sendiri, jadi
  //    konteks ini mulai tanpa sesi.
  // 2. Pengaturan retrieval. Test pengaturan menaikkan ambang kemiripan, dan
  //    nilai itu tersimpan di backend. Tanpa pemulihan, test retrieval
  //    berikutnya mewarisi ambang yang terlalu ketat dan gagal menemukan
  //    sumber yang sebenarnya ada.
  //
  // Memulihkan pengaturan butuh `ida_session`, bukan hanya `ida_gate`.
  // Versi sebelumnya hanya mengirim `ida_gate`, dijawab 401, dan karena
  // kegagalannya ditelan, ambang tidak pernah kembali ke nilai awal.
  const akar = baseURL ?? "http://127.0.0.1:3000";

  const login = await request
    .post(`${akar}/api/v1/auth/verify`, { data: { passcode: PASSCODE } })
    .catch(() => null);

  if (!login || !login.ok()) return;

  await request
    .put(`${akar}/api/v1/settings`, {
      data: { top_k: 5, similarity_threshold: AMBANG_E2E },
    })
    .catch(() => undefined);
});