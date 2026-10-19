import { expect, test } from "@playwright/test";
import { PASSCODE, chatInput, login } from "./fixtures";

/**
 * Gerbang akses: apa yang boleh dan tidak boleh dilihat tanpa passcode.
 *
 * Ini test yang dulu gagal diam-diam: halaman `/chat` terbuka (karena ada
 * penanda cookie), tapi setiap panggilan API kena 401 dan pengguna melihat
 * "sesi berakhir" di mana-mana.
 */
test.describe("gerbang akses", () => {
  test("halaman tanpa sesi dialihkan ke login", async ({ page }) => {
    await page.goto("/chat");
    await expect(page).toHaveURL(/\/login/);
  });

  test("login salah ditolak tanpa merusak halaman", async ({ page }) => {
    await page.goto("/login");
    await page.getByLabel("Passcode akses").fill("passcode-yang-salah");
    await page.getByRole("button", { name: "Masuk" }).click();
    // Alert milik form passcode, bukan `#__next-route-announcer__` yang
    // selalu ada di setiap halaman Next.js dan teksnya kosong. Tanpa
    // pembedaan ini, asersinya memeriksa elemen yang salah.
    await expect(page.locator("#passcode-feedback")).toContainText(/salah/i);
    await expect(page).toHaveURL(/\/login/);
  });

  test("login benar memberi akses penuh", async ({ page }) => {
    await login(page);
    await expect(chatInput(page))
      .toBeVisible();
  });

  test("tujuan dari login dipulihkan setelah masuk", async ({ page }) => {
    await page.goto("/documents");
    await expect(page).toHaveURL(/\/login\?next=%2Fdocuments/);
    await page.getByLabel("Passcode akses").fill(PASSCODE);
    await page.getByRole("button", { name: "Masuk" }).click();
    // `next` dipakai supaya pengguna kembali ke halaman yang tadi dibuka,
    // bukan selalu ke /chat.
    await expect(page).toHaveURL(/\/documents/);
  });

  test("logout mengembalikan ke login dan mengunci lagi", async ({ page }) => {
    await login(page);
    await page.getByRole("button", { name: /keluar dari demo/i }).click();
    await expect(page).toHaveURL(/\/login/);
    await page.goto("/analytics");
    await expect(page).toHaveURL(/\/login/);
  });
});

/**
 * `?next=` berasal dari URL, jadi siapa pun bisa mengisinya. Nilai itu
 * dipakai untuk `redirect()` setelah login, dan `redirect()` meneruskan
 * apa pun yang diberikan.
 *
 * Validasi lama hanya memeriksa tiga hal (diawali `/`, bukan `//`, bukan
 * `/\`), dan itu bisa dilewati dengan karakter kontrol: `"/\n/evil.example"`
 * lolos ketiga syarat itu, lalu dibaca browser sebagai `//evil.example`.
 * Yang diuji di sini adalah janji yang lebih kuat: setelah login, browser
 * harus tetap berada di origin aplikasi, apa pun isi `?next=`.
 */
test.describe("tujuan login tidak bisa dipakai keluar origin", () => {
  const jahat = [
    "//evil.example",
    "/\\evil.example",
    "https://evil.example",
    "/%5Cevil.example",
    "/\n/evil.example",
    "/\t/evil.example",
    "/%0d%0aLocation:%20//evil.example",
  ];

  for (const nilai of jahat) {
    test(`ditolak: ${JSON.stringify(nilai)}`, async ({ page }) => {
      await page.goto(`/login?next=${encodeURIComponent(nilai)}`);
      // Origin diambil setelah navigasi: sebelum itu `page.url()` masih
      // `about:blank`, dan origin-nya `"null"` sehingga perbandingan di
      // bawah akan selalu gagal.
      const origin = new URL(page.url()).origin;

      await page.getByLabel("Passcode akses").fill(PASSCODE);
      await page.getByRole("button", { name: "Masuk" }).click();

      // Yang penting bukan sekadar "tidak error", tapi tetap di origin ini.
      await expect(page).toHaveURL(/\/chat/);
      expect(new URL(page.url()).origin).toBe(origin);
    });
  }
});