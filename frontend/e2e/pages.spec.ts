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

    // `nth(1)` adalah slider ambang kemiripan; slider pertama adalah top-k.
    // `role="slider"` disandang thumb, dan di sanalah `aria-valuenow` berada.
    const threshold = page.getByRole("slider").nth(1);

    // Nilai sebelum diubah, supaya test tahu apakah nilainya benar-benar
    // berubah, bukan hanya "ada angka".
    const sebelum = await threshold.getAttribute("aria-valuenow");
    expect(sebelum, "aria-valuenow tidak terbaca dari slider").not.toBeNull();

    await threshold.focus();
    await page.keyboard.press("ArrowRight");
    await page.keyboard.press("ArrowRight");

    // Indikator penyimpanan muncul lalu hilang. Menunggu kemunculannya
    // sekaligus memastikan perubahan slider memang memicu penyimpanan.
    const menyimpan = page.getByText(/menyimpan/i);
    await expect(menyimpan).toBeVisible({ timeout: 5_000 });
    await expect(menyimpan).toBeHidden({ timeout: 15_000 });

    const sesudah = await threshold.getAttribute("aria-valuenow");
    expect(sesudah, "slider tidak berubah setelah ditekan").not.toBe(sebelum);

    await page.reload();
    // Setelah reload, nilai dari server harus sama dengan yang disimpan.
    // Kalau tidak, slider hanya mengubah tampilan lokal.
    const after = page.getByRole("slider").nth(1);
    await expect(after).toHaveAttribute("aria-valuenow", sesudah!);

    // Nilai yang tersimpan harus benar-benar berbeda dari nilai awal, bukan
    // sekadar "ada angka". Tanpa pemeriksaan ini, test bisa hijau walaupun
    // slider tidak pernah berubah.
    expect(sesudah).not.toBe(sebelum);
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
    // Dibaca dari dalam halaman, bukan lewat `page.request`: keduanya punya
    // cookie jar berbeda, dan kesimpulan test bisa berlawanan dengan yang
    // benar-benar dilihat UI.
    const health = await page.evaluate(async () => {
      const response = await fetch("/api/v1/health", { credentials: "include" });
      return response.json();
    });
    // Kondisi yang sama dengan `site-header.tsx`: banner muncul kalau status
    // degraded ATAU mode fallback-nya reduced. Memeriksa salah satu saja
    // membuat test menyimpulkan kebalikan dari yang dilihat pengguna.
    const terbatas =
      health.status === "degraded" || health.fallback?.mode === "reduced";

    if (terbatas) {
      await expect(banner).toBeVisible();
    } else {
      await expect(banner).toHaveCount(0);
    }
  });
});