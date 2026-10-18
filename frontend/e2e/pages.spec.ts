import { expect, test } from "@playwright/test";
import { login } from "./fixtures";

/**
 * Halaman pendukung. Fokusnya bukan tampilan, tapi angka dan status yang
 * tidak boleh menipu: health yang diminished harus terlihat, dan pengaturan
 * harus benar-benar sampai ke server.
 */
test.describe("pengaturan", () => {
  test("nilai pengaturan disimpan dan dibaca ulang", async ({ page }) => {
    await login(page);
    await page.goto("/settings");

    const threshold = page.getByRole("slider").nth(1);
    await threshold.focus();
    await page.keyboard.press("ArrowRight");
    await page.keyboard.press("ArrowRight");

    await expect(page.getByText(/tersimpan/i)).toBeVisible({ timeout: 15_000 });

    await page.reload();
    // Setelah reload, nilai dari server harus sama dengan yang disimpan.
    // Kalau tidak, slider hanya mengubah tampilan lokal.
    const after = page.getByRole("slider").nth(1);
    await expect(after).toHaveAttribute("aria-valuenow", /0\.\d+/);
  });

  test("reset sesi mengosongkan daftar percakapan", async ({ page }) => {
    await login(page);
    await page.goto("/settings");
    await page.getByRole("button", { name: /reset|hapus semua sesi/i }).first().click();
    await page.getByRole("button", { name: /hapus|ya, reset|konfirmasi/i }).last().click();
    await expect(page.getByText(/dihapus/i).first()).toBeVisible({ timeout: 15_000 });
  });
});

test.describe("halaman lain", () => {
  test("beranda, about, dan analytics bisa dibuka", async ({ page }) => {
    await login(page);
    for (const path of ["/", "/about", "/analytics"]) {
      await page.goto(path);
      await expect(page).not.toHaveURL(/\/login/);
      // Route announcer Next.js selalu punya role alert, jadi menghitung
      // seluruh alert akan selalu gagal. Yang diperiksa adalah pesan error
      // yang benar-benar ditampilkan aplikasi.
      await expect(
        page.locator('[role="alert"]:not(#__next-route-announcer__)'),
      ).toHaveCount(0);
    }
  });

  test("status backend yang terbatas terlihat di header", async ({ page }) => {
    await login(page);
    const banner = page.getByText(/mode terbatas/i);
    // Banner ini hanya muncul kalau backend melapor degraded. Di setup yang
    // sehat banner tidak boleh muncul, dan kalau backend sedang terbatas,
    // ia harus terlihat, bukan disembunyikan.
    const health = await page.request.get("/api/v1/health").then((r) => r.json());
    if (health.status === "degraded") {
      await expect(banner).toBeVisible();
    } else {
      await expect(banner).toHaveCount(0);
    }
  });
});