import { expect, test } from "@playwright/test";
import {
  gabungScope,
  hapusPilihanTerpilih,
  pemilihBolehDiubah,
} from "@/lib/chat/scope";

/**
 * Uji logika scope tanpa browser.
 *
 * Ditempatkan di suite Playwright, bukan di file sementara, karena tooling test
 * di proyek ini hanya itu. Test-nya sendiri tidak menyentuh browser, jadi
 * berjalan cepat dan tetap ikut dijalankan di CI bersama spec lain.
 *
 * Alasan logika ini diuji terpisah dari UI: bug yang pernah terjadi adalah
 * `?doc=` digabungkan ke tampilan pemilih tetapi tidak ke nilai yang dikirim
 * ke backend. Dari layar semuanya terlihat benar, dan yang salah hanya isi
 * request. Memeriksa hasil penggabungan secara langsung menutup celah itu
 * tanpa bergantung pada selektor.
 */
test.describe("logika scope dokumen", () => {
  test("tanpa dokumen terkunci, pilihan dipakai apa adanya", () => {
    expect(gabungScope(null, [])).toEqual([]);
    expect(gabungScope(null, ["a", "b"])).toEqual(["a", "b"]);
  });

  test("dokumen terkunci selalu ikut terkirim", () => {
    // Inilah inti kebocoran scope: kalau dokumen dari `?doc=` tidak ikut,
    // pencarian melebar sementara label di layar menyatakan dibatasi.
    expect(gabungScope("x", [])).toEqual(["x"]);
    expect(gabungScope("x", ["a"])).toEqual(["x", "a"]);
    expect(gabungScope("x", ["a", "b"])).toContain("x");
  });

  test("dokumen terkunci tidak terduplikasi", () => {
    expect(gabungScope("x", ["x", "a"])).toEqual(["x", "a"]);
    expect(new Set(gabungScope("x", ["x"])).size).toBe(1);
  });

  test("hapus pilihan mempertahankan dokumen terkunci", () => {
    expect(hapusPilihanTerpilih(null, ["a", "b"])).toEqual([]);
    expect(hapusPilihanTerpilih("x", ["x", "a"])).toEqual(["x"]);
  });

  test("pemilih beku hanya saat ada dokumen terkunci", () => {
    expect(pemilihBolehDiubah(null)).toBe(true);
    expect(pemilihBolehDiubah("x")).toBe(false);
  });
});
