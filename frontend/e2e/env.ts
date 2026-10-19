/**
 * Konstanta bersama untuk test E2E.
 *
 * Dipisah dari `fixtures.ts` karena `globalSetup` tidak boleh memuat fixture
 * test: berkas itu memanggil `test.beforeEach` di tingkat modul, dan memuatnya
 * di luar konteks test menghasilkan error.
 */

/**
 * Passcode yang dipakai test.
 *
 * Diambil dari `E2E_PASSCODE` karena nilainya tidak boleh ditulis mati di
 * test: passcode demo yang sama di semua clone membuat verifikasi ini tidak
 * berarti apa-apa.
 */
export const PASSCODE = process.env.E2E_PASSCODE ?? "uji-e2e";

/**
 * Ambang kemiripan untuk E2E.
 *
 * Sama dengan default produksi (0,82). E2E memakai model embedding asli, jadi
 * ambang ini memang berlaku, dan test sitasi lulus karena retrieval-nya benar,
 * bukan karena ambangnya diturunkan.
 *
 * Sebelumnya E2E memakai embedding stub hashing, yang hanya memberi skor
 * sekitar 0,49; dengan ambang 0,82 setiap pertanyaan dijawab "tidak
 * ditemukan". Itu bukan bug, melainkan konsekuensi stub, dan penyelesaiannya
 * adalah memakai model asli, bukan menurunkan ambang.
 */
export const AMBANG_E2E = 0.82;
