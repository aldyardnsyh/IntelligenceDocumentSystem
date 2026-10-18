/**
 * Logika penggabungan scope dokumen, dipisah supaya bisa diuji tanpa browser.
 *
 * Bug yang dicegah di sini nyata dan pernah terjadi: `?doc=` digabungkan ke
 * tampilan pemilih, tapi nilai yang dikirim ke backend tetap pilihan manual.
 * Label di layar menyatakan pencarian dibatasi, sedangkan pencarian sebenarnya
 * melebar ke semua dokumen. Itu kebocoran scope yang tidak terlihat di UI.
 */

/**
 * Gabungkan dokumen dari `?doc=` dengan pilihan manual.
 *
 * Dokumen dari `?doc=` selalu ada di depan dan tidak pernah hilang, karena
 * tautan "Tanya dokumen ini" adalah pernyataan eksplisit pengguna tentang
 * dokumen mana yang ingin ditanyai.
 */
export function gabungScope(lockedId: string | null, picked: string[]): string[] {
  if (!lockedId) return picked;
  if (picked.includes(lockedId)) return picked;
  return [lockedId, ...picked];
}

/** Apakah pemilih boleh diubah. Dokumen terkunci membuat pemilih beku. */
export function pemilihBolehDiubah(lockedId: string | null): boolean {
  return lockedId === null;
}

/** Sisa pilihan setelah tombol hapus, dengan dokumen terkunci dipertahankan. */
export function hapusPilihanTerpilih(
  lockedId: string | null,
  picked: string[],
): string[] {
  if (!lockedId) return [];
  return picked.filter((id) => id === lockedId);
}
