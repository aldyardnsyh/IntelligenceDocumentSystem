import { expect, test, type Page } from "@playwright/test";

/**
 * Helper lokal, sengaja tidak diimpor dari `./fixtures`.
 *
 * Modul itu mendaftarkan `test.beforeEach` global yang memanggil backend
 * (`/api/v1/auth/verify` lalu `PUT /api/v1/settings`). Di mode demo tidak ada
 * backend, jadi request itu menembus proxy ke port 8000 dan menggagalkan
 * setiap test sebelum halaman sempat diuji. Helper di bawah hanya menyentuh
 * yang benar-benar dirender di peramban.
 */
function chatInput(page: Page) {
  return page.getByPlaceholder(/tanyakan sesuatu tentang dokumen|tulis pertanyaan/i);
}

async function uploadSample(page: Page, filename: string) {
  const chooser = page.waitForEvent("filechooser");
  await page.getByRole("button", { name: /unggah|tarik dan lepas/i }).first().click();
  const fileChooser = await chooser;
  await fileChooser.setFiles(`../backend/samples/${filename}`);
}

/**
 * Mode demo publik: profil tanpa backend (`NEXT_PUBLIC_USE_BACKEND=0`) dengan
 * jalur masuk tanpa passcode (`NEXT_PUBLIC_DEMO_ENTRY=1`).
 *
 * Seluruh test di sini menekan tombol yang benar-benar dilihat pengunjung dan
 * memeriksa teks yang benar-benar dirender. Tidak ada passcode, tidak ada
 * panggilan API langsung, karena yang dijanjikan mode demo adalah "buka, klik
 * sekali, langsung bisa bertanya".
 *
 * Setiap test berjalan di konteks peramban baru, jadi localStorage mulai dari
 * seed yang sama: tiga dokumen contoh dan belum ada riwayat percakapan.
 */

const DOKUMEN_CONTOH = [
  "contoh-sop-layanan.md",
  "panduan-tiket-layanan.md",
  "kebijakan-cuti.md",
] as const;

const NAMA_PDF = "laporan-infrastruktur.pdf";

/** Pertanyaan yang jawabannya ada di `contoh-sop-layanan.md`. */
const PERTANYAAN_SITASI =
  "Berapa lama target penyelesaian permintaan menurut SOP layanan?";

/** Pertanyaan yang tidak punya jawaban di korpus mana pun. */
const PERTANYAAN_LUAR_KORPUS = "Berapa gaji direktur utama?";

/**
 * Pertanyaan yang jawabannya ada di `laporan-infrastruktur.pdf`
 * ("Target uptime 99% per bulan" pada bagian Ketersediaan).
 */
const PERTANYAAN_PDF = "Berapa target uptime per bulan?";

/**
 * Masuk lewat tombol demo, bukan lewat cookie atau API.
 *
 * Diuji sebagai pengguna: halaman /login, satu tombol, lalu kotak tanya harus
 * sudah bisa dipakai. Kalau tombolnya hilang karena flag env salah, pesan
 * kegagalan di bawah langsung menyebut sebabnya.
 */
async function masukDemo(page: Page) {
  await page.goto("/login");

  const tombol = page.getByRole("button", { name: "Masuk demo" });
  await expect(
    tombol,
    'tombol "Masuk demo" tidak tampil; pastikan NEXT_PUBLIC_USE_BACKEND=0 dan NEXT_PUBLIC_DEMO_ENTRY=1',
  ).toBeVisible({ timeout: 20_000 });

  await tombol.click();

  await expect(
    page,
    "setelah menekan Masuk demo, halaman tidak berpindah ke /chat",
  ).toHaveURL(/\/chat(?:\/|\?|$)/, { timeout: 20_000 });

  await expect(
    chatInput(page),
    "kotak tanya tidak muncul setelah masuk demo",
  ).toBeVisible({ timeout: 20_000 });
}

/** Kartu dokumen, dicari lewat nama berkas yang terlihat pengguna. */
function kartuDokumen(page: Page, nama: string) {
  return page.getByTestId("document-card").filter({ hasText: nama }).first();
}

/**
 * Tunggu dokumen selesai diindeks, dengan batas waktu eksplisit 60 detik.
 *
 * Pemeriksaan dilakukan dengan polling pada teks kartu, bukan sekali baca:
 * status berubah dari "Memproses..." ke "Siap ditanyai" setelah ingestion.
 * 60 detik adalah batas yang diminta; kalau lebih lama, itu kegagalan yang
 * harus terlihat, bukan sesuatu yang ditunggu tanpa akhir.
 */
async function tungguDokumenSiap(page: Page, nama: string) {
  const kartu = kartuDokumen(page, nama);
  await expect(kartu, `kartu dokumen "${nama}" tidak muncul`).toBeVisible({
    timeout: 30_000,
  });

  await expect
    .poll(async () => (await kartu.innerText()).toLowerCase(), {
      timeout: 60_000,
      message: `dokumen "${nama}" tidak mencapai status siap dalam 60 detik`,
    })
    .toMatch(/siap/);
}

test.describe("gerbang demo", () => {
  test("masuk demo satu klik", async ({ page }) => {
    await page.goto("/login");

    const tombol = page.getByRole("button", { name: "Masuk demo" });
    await expect(tombol, 'tombol "Masuk demo" tidak terlihat').toBeVisible({
      timeout: 20_000,
    });

    await tombol.click();

    await expect(page, "URL tidak berubah menjadi /chat").toHaveURL(
      /\/chat(?:\/|\?|$)/,
      { timeout: 20_000 },
    );
    await expect(chatInput(page), "kotak tanya tidak terlihat").toBeVisible({
      timeout: 20_000,
    });
  });
});

test.describe("dokumen contoh", () => {
  test.beforeEach(async ({ page }) => {
    await masukDemo(page);
  });

  test("dokumen contoh tersedia", async ({ page }) => {
    await page.goto("/documents");

    for (const nama of DOKUMEN_CONTOH) {
      await expect(
        page.getByRole("link", { name: nama, exact: true }),
        `dokumen contoh "${nama}" tidak tampil di /documents`,
      ).toBeVisible({ timeout: 30_000 });
    }
  });
});

test.describe("jawaban bersitasi", () => {
  test.beforeEach(async ({ page }) => {
    await masukDemo(page);
  });

  test("jawaban bersitasi", async ({ page }) => {
    await page.goto("/chat");

    const input = chatInput(page);
    await input.fill(PERTANYAAN_SITASI);
    await input.press("Enter");

    // Panel sumber tertutup secara default, tetapi pemicunya ("N sumber
    // ditemukan") sudah menjadi bukti bahwa jawaban membawa sitasi.
    const pemicuSumber = page
      .getByRole("button", { name: /sumber ditemukan/i })
      .last();
    await expect(
      pemicuSumber,
      "jawaban tidak menampilkan teks sumber/sitasi",
    ).toBeVisible({ timeout: 30_000 });

    await pemicuSumber.click();

    await expect(
      page.getByRole("link", { name: /contoh-sop-layanan\.md/i }).first(),
      "tidak ada tautan sitasi yang menunjuk ke dokumen SOP",
    ).toBeVisible({ timeout: 15_000 });
  });
});

test.describe("informasi tidak ditemukan", () => {
  test.beforeEach(async ({ page }) => {
    await masukDemo(page);
  });

  test("tidak ditemukan", async ({ page }) => {
    await page.goto("/chat");

    const input = chatInput(page);
    await input.fill(PERTANYAAN_LUAR_KORPUS);
    await input.press("Enter");

    // Jawaban penolakan harus muncul lebih dulu, supaya pemeriksaan "tidak ada
    // kartu sitasi" di bawah tidak lolos hanya karena jawaban belum dirender.
    await expect(
      page.getByText(/tidak ditemukan/i).first(),
      "sistem tidak menyatakan informasi tidak ditemukan",
    ).toBeVisible({ timeout: 30_000 });

    await expect(
      page.getByRole("button", { name: /sumber ditemukan/i }),
      "jawaban 'tidak ditemukan' tidak boleh membawa kartu sitasi",
    ).toHaveCount(0);
  });
});

test.describe("unggah PDF", () => {
  test.beforeEach(async ({ page }) => {
    await masukDemo(page);
  });

  test("unggah PDF lalu tanya", async ({ page }) => {
    // Unggah + polling status + tanya jawab memakai anggaran waktu lebih dari
    // batas default 60 detik per test. Batas polling statusnya sendiri tetap
    // 60 detik, sesuai ketentuan.
    test.setTimeout(150_000);

    await page.goto("/documents");
    await uploadSample(page, NAMA_PDF);
    await tungguDokumenSiap(page, NAMA_PDF);

    await page.goto("/chat");

    const input = chatInput(page);
    await input.fill(PERTANYAAN_PDF);
    await input.press("Enter");

    const pemicuSumber = page
      .getByRole("button", { name: /sumber ditemukan/i })
      .last();
    await expect(
      pemicuSumber,
      "jawaban atas isi PDF tidak menyertakan sumber",
    ).toBeVisible({ timeout: 30_000 });

    await pemicuSumber.click();

    await expect(
      page.getByRole("link", { name: /laporan-infrastruktur\.pdf/i }).first(),
      "sitasi tidak menunjuk ke PDF yang baru diunggah",
    ).toBeVisible({ timeout: 15_000 });

    await expect(
      page.getByText(/uptime 99\s*%/i).first(),
      "isi PDF (target uptime 99%) tidak muncul di jawaban",
    ).toBeVisible({ timeout: 15_000 });
  });
});

test.describe("reset data demo", () => {
  test.beforeEach(async ({ page }) => {
    await masukDemo(page);
  });

  test("reset data demo", async ({ page }) => {
    test.setTimeout(120_000);

    // Prasyarat: unggah satu dokumen yang bukan bagian dari data contoh.
    // Tanpa ini, "hanya tiga dokumen contoh" sudah benar sebelum reset dan
    // test tidak membuktikan apa pun. `kebijakan-cuti.txt` sengaja berbeda
    // dari contoh `kebijakan-cuti.md` supaya bisa dibedakan.
    await page.goto("/documents");
    await uploadSample(page, "kebijakan-cuti.txt");
    await tungguDokumenSiap(page, "kebijakan-cuti.txt");

    await page.goto("/settings");
    await page.getByRole("button", { name: "Reset data demo" }).click();
    await page.getByRole("button", { name: "Ya, reset data" }).click();

    await page.goto("/documents");

    await expect(
      page.getByTestId("document-card"),
      "jumlah dokumen setelah reset bukan tiga",
    ).toHaveCount(DOKUMEN_CONTOH.length, { timeout: 20_000 });

    for (const nama of DOKUMEN_CONTOH) {
      await expect(
        page.getByRole("link", { name: nama, exact: true }),
        `dokumen contoh "${nama}" tidak kembali setelah reset`,
      ).toBeVisible({ timeout: 20_000 });
    }

    await expect(
      page.getByRole("link", { name: "kebijakan-cuti.txt", exact: true }),
      "dokumen unggahan masih ada setelah reset",
    ).toHaveCount(0);
  });
});