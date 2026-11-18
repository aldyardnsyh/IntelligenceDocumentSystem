/**
 * Konstanta produk yang dipakai lintas halaman.
 *
 * Semula hidup di fixture demo (``lib/mock``); sejak mode demo dihapus,
 * tempat yang benar adalah modul netral seperti ini supaya tidak ada
 * komponen yang mengimpor dari kode yang sudah tidak ada.
 */

/** Batas ukuran unggahan, disetujui backend (FR-1.1). */
export const MAX_FILE_BYTES = 10 * 1024 * 1024;

/** Ekstensi yang diterima backend. */
export const ACCEPTED_EXTENSIONS = [".pdf", ".txt", ".md", ".markdown"] as const;

/** Batas panjang judul sesi (sama dengan backend, PATCH /chat/sessions). */
export const SESSION_TITLE_MAX_LENGTH = 80;
