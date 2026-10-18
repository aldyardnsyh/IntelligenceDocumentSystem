import { expect, test } from "@playwright/test";
import { login } from "./fixtures";

/**
 * Halaman analytics harus punya jalan keluar, bukan hanya memberi tahu ada
 * yang kurang.
 *
 * Bug yang pernah terjadi: halaman menampilkan "belum ada data evaluasi" dan
 * menyuruh menjalankan job evaluasi, tanpa memberi tahu caranya, dan
 * satu-satunya cara yang ada butuh API key yang mungkin belum dimiliki
 * pengguna.
 */
test.describe("evaluasi & observability", () => {
  test("halaman analytics menjelaskan isinya", async ({ page }) => {
    await login(page);
    await page.goto("/analytics");
    // `level: 1` wajib. Tanpa itu, judul halaman dan subjudul "Belum ada data
    // evaluasi" sama-sama cocok, dan Playwright menolak memilih di antara
    // keduanya (strict mode). Yang dimaksud test ini adalah judul halaman.
    await expect(
      page.getByRole("heading", { level: 1, name: /evaluasi/i }),
    ).toBeVisible();
    // Penjelasan apa yang diukur harus ada, bukan sekadar judul.
    await expect(page.getByText(/precision|latensi|log query/i).first()).toBeVisible();
  });

  test("evaluasi bisa dijalankan dari halaman", async ({ page }) => {
    await login(page);
    await page.goto("/analytics");

    const button = page.getByRole("button", { name: /jalankan evaluasi/i });
    // Tombol hanya ada saat belum ada data evaluasi. Kalau sudah ada, test
    // ini tidak berlaku.
    if ((await button.count()) === 0) {
      test.skip(true, "sudah ada data evaluasi");
    }

    await button.click();
    // Dua hasil yang mungkin: sukses (kartu skor muncul) atau pesan yang
    // menjelaskan kenapa belum bisa. Yang tidak boleh: diam tanpa umpan balik.
    const sukses = page.getByText(/evaluasi selesai/i);
    const gagal = page.getByText(/belum ada di korpus|dataset|tidak ditemukan/i);
    await expect(sukses.or(gagal).first()).toBeVisible({ timeout: 90_000 });
  });

  test("jejak latensi terisi setelah bertanya", async ({ page }) => {
    await login(page);
    await page.goto("/chat");
    const input = page.getByPlaceholder(/tanyakan sesuatu|tulis pertanyaan/i);
    await input.fill("berapa hari SLA penyelesaian?");
    await input.press("Enter");
    // Tunggu jawaban selesai.
    await expect(page.getByText(/SUMBER|tidak ditemukan/i).first()).toBeVisible({
      timeout: 45_000,
    });

    await page.goto("/analytics");
    await expect(page.getByText(/latensi|log query/i).first()).toBeVisible();
    // Log query harus memuat pertanyaan yang baru saja diajukan.
    await expect(page.getByText(/berapa hari SLA penyelesaian/i).first()).toBeVisible({
      timeout: 20_000,
    });
  });
});

/**
 * Restart backend harus berarti mulai bersih.
 *
 * Sesi akses dan riwayat hidup di memori proses. Setelah restart keduanya
 * kosong, jadi mempertahankan penanda login hanya membuat pengguna menemukan
 * riwayat yang tidak bisa dibuka.
 */
test.describe("reset setelah backend dijalankan ulang", () => {
  test("boot id berubah berarti sesi browser dibuang", async ({ page }) => {
    await login(page);

    // Simulasikan backend baru: boot_id lama disimpan, lalu dibandingkan
    // dengan yang sekarang. Nilai yang berbeda harus memaksa login ulang.
    const health = await page.request.get("/api/v1/health").then((r) => r.json());
    const bootId = health.fallback?.boot_id;
    test.skip(!bootId, "backend tidak melaporkan boot_id");

    await page.evaluate(
      ([key, value]) => window.localStorage.setItem(key, value),
      ["ida_boot_id", "boot-id-yang-sudah-tidak-berlaku"],
    );

    // Muat ulang: aplikasi harus mendeteksi perbedaan dan mengalihkan ke login.
    await page.goto("/chat");
    await expect(page).toHaveURL(/\/login/, { timeout: 20_000 });
  });
});