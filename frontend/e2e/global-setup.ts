import type { FullConfig } from "@playwright/test";
import { AMBANG_E2E, PASSCODE } from "./env";

/**
 * Membersihkan dokumen dan sesi sebelum seluruh suite berjalan.
 *
 * Setiap test mengunggah berkas dan tidak ada yang menghapusnya. Tanpa
 * pembersihan, korpus menumpuk antar run, dan akibatnya berlapis:
 *
 * - Test yang memeriksa "kartu dengan nama ini hilang" gagal karena masih ada
 *   puluhan kartu lain dengan nama sama.
 * - Pemilih scope berisi entri kembar, sehingga selector ambigu.
 * - Retrieval memburuk karena puluhan dokumen serupa bersaing, dan pertanyaan
 *   yang seharusnya menemukan sumber berubah menjadi "tidak ada bagian
 *   dokumen yang cukup mirip". Test sitasi lalu gagal karena data, bukan kode.
 *
 * CI selalu mulai dari database kosong, jadi pembersihan ini membuat run di
 * komputer pengembang berperilaku sama dengan CI.
 *
 * Kalau backend tidak bisa dihubungi, setup ini TIDAK gagal: Playwright akan
 * melaporkan kegagalan yang lebih jelas di test pertama. Menggagalkan setup
 * hanya menyembunyikan pesan aslinya.
 */
export default async function globalSetup(config: FullConfig) {
  const baseURL =
    process.env.E2E_BASE_URL ??
    config.projects[0]?.use?.baseURL ??
    "http://localhost:3000";

  const login = await fetch(`${baseURL}/api/v1/auth/verify`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ passcode: PASSCODE }),
  }).catch(() => null);

  if (!login || !login.ok) {
    console.warn(
      "[e2e] Backend belum siap saat globalSetup; pembersihan dilewati.",
    );
    return;
  }

  // Cookie sesi dari backend perlu ikut dipakai untuk menghapus.
  const cookie = login.headers
    .getSetCookie()
    .map((bagian) => bagian.split(";")[0])
    .join("; ");

  const headers = { cookie: `ida_gate=1; ${cookie}` };

  const dokumen = await fetch(`${baseURL}/api/v1/documents`, { headers })
    .then((r) => (r.ok ? r.json() : []))
    .catch(() => [] as Array<{ id: string }>);

  for (const item of dokumen as Array<{ id: string }>) {
    await fetch(`${baseURL}/api/v1/documents/${item.id}`, {
      method: "DELETE",
      headers,
    }).catch(() => undefined);
  }

  await fetch(`${baseURL}/api/v1/chat/sessions`, {
    method: "DELETE",
    headers,
  }).catch(() => undefined);

  // Kembalikan pengaturan retrieval ke nilai awal. Test pengaturan mengubah
  // ambang kemiripan, dan nilai yang tertinggal membuat test retrieval lain
  // gagal karena ambangnya terlalu ketat.
  await fetch(`${baseURL}/api/v1/settings`, {
    method: "PUT",
    headers: { ...headers, "content-type": "application/json" },
    body: JSON.stringify({ top_k: 5, similarity_threshold: AMBANG_E2E }),
  }).catch(() => undefined);

  console.log(`[e2e] Membersihkan ${(dokumen as unknown[]).length} dokumen.`);
}


/**
 * Kembalikan pengaturan retrieval ke nilai awal.
 *
 * Dipakai `globalSetup` sekali di awal, dan `fixtures.beforeEach` sebelum
 * setiap test. Test pengaturan mengubah ambang kemiripan, dan nilai itu
 * tersimpan di backend, sehingga tanpa pemulihan test berikutnya mewarisi
 * ambang yang terlalu ketat dan gagal menemukan sumber.
 */
export async function pulihkanPengaturan(baseURL: string): Promise<void> {
  const login = await fetch(`${baseURL}/api/v1/auth/verify`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ passcode: PASSCODE }),
  }).catch(() => null);
  if (!login || !login.ok) return;

  const cookie = login.headers
    .getSetCookie()
    .map((bagian) => bagian.split(";")[0])
    .join("; ");

  await fetch(`${baseURL}/api/v1/settings`, {
    method: "PUT",
    headers: {
      cookie: `ida_gate=1; ${cookie}`,
      "content-type": "application/json",
    },
    body: JSON.stringify({ top_k: 5, similarity_threshold: 0.82 }),
  }).catch(() => undefined);
}
