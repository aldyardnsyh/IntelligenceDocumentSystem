import { toast } from "sonner";
import { ApiError } from "@/lib/api/error";

/**
 * Satu pintu untuk semua notifikasi.
 *
 * Sebelumnya setiap komponen memanggil `toast.success(...)` / `toast.error(...)`
 * langsung dengan kalimat yang berbeda-beda: ada yang menyebut nama berkas,
 * ada yang tidak; ada yang menjelaskan langkah berikutnya, ada yang hanya
 * "berhasil". Hasilnya notifikasi terasa acak, dan yang paling sering
 * hilang adalah **apa yang harus dilakukan setelah ini**.
 *
 * Di sini bentuknya diseragamkan:
 * - judul  : apa yang terjadi, singkat
 * - detail : konteks atau langkah berikutnya (opsional)
 *
 * Panjang detail dijaga wajar; notifikasi bukan tempat menulis paragraf.
 */

function trimDetail(detail: string | undefined, max = 160): string | undefined {
  if (!detail) return undefined;
  const clean = detail.trim().replace(/\s+/g, " ");
  if (clean.length === 0) return undefined;
  return clean.length > max ? `${clean.slice(0, max - 1)}...` : clean;
}

export const notify = {
  /** Sesuatu berhasil, dan hasilnya sudah terlihat pengguna. */
  success(title: string, detail?: string) {
    toast.success(title, { description: trimDetail(detail) });
  },

  /** Sesuatu gagal. Detail sebaiknya menyebut penyebab atau langkah berikutnya. */
  error(title: string, detail?: string) {
    toast.error(title, { description: trimDetail(detail) });
  },

  /** Berhasil, tapi ada hal yang perlu diperhatikan. */
  warning(title: string, detail?: string) {
    toast.warning(title, { description: trimDetail(detail) });
  },

  /** Bukan hasil aksi: pemberitahuan atau penjelasan. */
  info(title: string, detail?: string) {
    toast.info(title, { description: trimDetail(detail) });
  },

  /** Aksi sedang berjalan. Kembalikan id-nya untuk ditutup nanti. */
  loading(title: string, detail?: string) {
    return toast.loading(title, { description: trimDetail(detail) });
  },

  /** Tutup notifikasi loading dengan hasil akhirnya. */
  settle(
    id: string | number,
    outcome: "success" | "error" | "info",
    title: string,
    detail?: string,
  ) {
    toast[outcome](title, { id, description: trimDetail(detail) });
  },

  /**
   * Notifikasi untuk error yang datang dari API.
   *
   * Judul tetap dari pemanggil (konteks aksinya), sedangkan pesan server
   * dipakai sebagai detail, itulah yang menjelaskan penyebabnya.
   */
  fromApiError(title: string, error: unknown, fallbackDetail?: string) {
    if (error instanceof ApiError) {
      // Pesan 401/403 sudah punya kalimat baku yang jelas; status lain
      // memakai detail server apa adanya.
      notify.error(title, error.message || fallbackDetail);
      return;
    }
    notify.error(title, fallbackDetail);
  },
};