import { expect, test } from "@playwright/test";
import { login, PASSCODE } from "./fixtures";

/**
 * Passcode: hint di layar login dan verifikasi harus sepakat.
 *
 * Bug yang pernah terjadi: hint di layar login menampilkan passcode contoh
 * yang ditulis mati di kode (`demo-rag-2025`), sementara backend memverifikasi
 * passcode lain. Pengguna mengetik passcode dari hint, ditolak, lalu
 * menyimpulkan aplikasinya rusak, padahal passcode-nya memang beda.
 */
test.describe("passcode", () => {
  test("passcode yang dinyatakan hint benar-benar diterima", async ({ page }) => {
    await page.goto("/login");
    const hint = page.getByText(/mode pengembangan\. passcode:/i);
    // Hint boleh tidak muncul (saat backend aktif dan operator tidak mengisi
    // NEXT_PUBLIC_DEV_PASSCODE_HINT). Yang tidak boleh: hint muncul tapi
    // salah.
    if ((await hint.count()) === 0) {
      test.skip(true, "hint tidak diaktifkan di environment ini");
    }

    const shown = (await hint.textContent())?.match(/passcode:\s*(\S+)/i)?.[1];
    expect(shown, "hint harus memuat passcode").toBeTruthy();

    await page.getByLabel("Passcode akses").fill(shown!);
    await page.getByRole("button", { name: "Masuk" }).click();
    // Kalau passcode dari hint ditolak, hint itu berbohong.
    await expect(page).toHaveURL(/\/chat/, { timeout: 20_000 });
  });

  test("passcode E2E yang dikonfigurasi diterima", async ({ page }) => {
    await login(page, PASSCODE);
    await expect(page).toHaveURL(/\/chat/);
  });
});
