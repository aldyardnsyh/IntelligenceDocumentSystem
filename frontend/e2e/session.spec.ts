import { expect, test } from "@playwright/test";
import { login, PASSCODE } from "./fixtures";

/**
 * Sesi harus bertahan melewati perpindahan halaman.
 *
 * Dua bug nyata pernah membuat ini gagal, dan keduanya lolos dari test lain
 * karena test lain memeriksa halaman login, bukan halaman setelahnya.
 *
 * Bug pertama: cookie `ida_gate` diset dengan `secure: NODE_ENV ===
 * "production"`. Saat aplikasi dijalankan sebagai build produksi di
 * `http://127.0.0.1`, browser membuang cookie `Secure`, proxy tidak melihat
 * sesi, dan setiap perpindahan halaman memantul ke /login.
 *
 * Bug kedua: cookie `ida_session` dari backend dinaikkan menjadi `Secure` oleh
 * frontend walaupun backend mengirimnya tanpa atribut itu. Login berhasil,
 * tetapi setiap request API berikutnya dijawab 401 `session_expired`.
 *
 * Gejala gabungannya di CI: login tampak berhasil, lalu tabel dokumen kosong
 * dan 26 test gagal dengan `getByRole('row') ... element(s) not found`.
 */
test.describe("sesi bertahan setelah login", () => {
  test("cookie gate dan cookie sesi tersimpan setelah login", async ({ page }) => {
    await login(page);

    const cookies = await page.context().cookies();
    const gate = cookies.find((item) => item.name === "ida_gate");
    const session = cookies.find((item) => item.name === "ida_session");

    // `ida_gate` menjaga proxy, `ida_session` menjaga API backend. Keduanya
    // harus ada, karena masing-masing menutup lapisan yang berbeda.
    expect(gate, "cookie ida_gate tidak tersimpan").toBeTruthy();
    expect(session, "cookie ida_session tidak tersimpan").toBeTruthy();
  });

  test("berpindah ke halaman dokumen tidak memantul ke login", async ({ page }) => {
    await login(page);
    await page.goto("/documents");

    // Ini asersi yang benar-benar menangkap bug cookie. Sebelumnya, memeriksa
    // halaman /chat setelah login tidak cukup: halamannya bisa terbuka
    // sementara perpindahan berikutnya memantul.
    await expect(page).toHaveURL(/\/documents/);
    await expect(page).not.toHaveURL(/\/login/);
  });

  test("permintaan API setelah login tidak dijawab session_expired", async ({ page }) => {
    await login(page);

    // Dipanggil dari dalam halaman, jadi cookie ikut terkirim seperti yang
    // dilakukan aplikasi. Yang diperiksa adalah status, bukan isinya: 401
    // berarti sesi backend tidak tersimpan.
    const status = await page.evaluate(async () => {
      const response = await fetch("/api/v1/documents", { credentials: "include" });
      return response.status;
    });
    expect(status, "API menolak sesi padahal baru saja login").toBe(200);
  });

  test("login dengan passcode benar beberapa kali berturut-turut tetap berhasil", async ({
    page,
  }) => {
    // Rate limit lokal di frontend berlaku per IP untuk percobaan GAGAL.
    // Test ini memastikan percobaan yang berhasil tidak ikut terhitung, dan
    // bahwa sesi tidak "bocor" antar login.
    for (let ke = 1; ke <= 3; ke += 1) {
      await page.context().clearCookies();
      await page.goto("/login");
      await page.getByLabel("Passcode akses").fill(PASSCODE);
      await page.getByRole("button", { name: "Masuk" }).click();
      await expect(page, `login ke-${ke} gagal`).toHaveURL(/\/chat/);
    }
  });
});
