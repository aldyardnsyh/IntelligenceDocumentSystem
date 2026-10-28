/**
 * Satu sumber keputusan produk untuk jalur masuk demo.
 *
 * Tombol "Masuk demo" di UI dan server action yang menanganinya harus membaca
 * nilai yang sama persis. Kalau tombolnya dirender dari satu kondisi dan
 * action-nya memakai kondisi lain, pengguna bisa melihat tombol yang selalu
 * gagal, atau lebih buruk lagi jalur masuk tanpa passcode tetap hidup padahal
 * tidak diniatkan.
 *
 * `isMockMode` saja tidak cukup. Mode fixture juga dipakai untuk pengembangan
 * lokal, di mana masuk tanpa passcode justru mengacaukan uji alur login; jadi
 * jalur demo butuh sakelar produk sendiri (`NEXT_PUBLIC_DEMO_ENTRY`).
 */

import { isMockMode } from "@/lib/api/config";

/**
 * Salinan lokal dari `readFlag` milik `@/lib/api/config`. Fungsi aslinya tidak
 * diekspor dari sana, dan modul ini tidak boleh mengubah file config pada
 * langkah ini. Pola nilainya sengaja identik: `1`, `true`, `yes`, `on`.
 */
export function readFlag(value: string | undefined): boolean {
  return /^(1|true|yes|on)$/i.test(value?.trim() ?? "");
}

/** True kalau jalur masuk demo tanpa passcode boleh ditampilkan. */
export const isDemoEntryEnabled = isMockMode && readFlag(process.env.NEXT_PUBLIC_DEMO_ENTRY);