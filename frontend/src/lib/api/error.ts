import type { ApiErrorBody } from "@/types/api";

/**
 * Error yang selalu membawa status HTTP supaya UI bisa membedakan
 * "tidak ditemukan" dari "server sedang tidak merespons".
 */
export class ApiError extends Error {
  readonly status: number;
  readonly code?: string;
  readonly retryAfterSeconds?: number;

  constructor(
    message: string,
    status: number,
    options: { code?: string; retryAfterSeconds?: number } = {},
  ) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = options.code;
    this.retryAfterSeconds = options.retryAfterSeconds;
  }

  get isRateLimited() {
    return this.status === 429;
  }

  get isAuthFailure() {
    return this.status === 401 || this.status === 403;
  }

  get isNotFound() {
    return this.status === 404;
  }

  /**
   * 5xx dan timeout: layak dicoba ulang.
   *
   * 507 dikecualikan walaupun berawalan 5. Kuota penyimpanan yang penuh tidak
   * akan berubah karena dicoba ulang; mencoba tiga kali hanya membuat
   * pengguna menunggu lebih lama sebelum melihat pesan yang sama, dan
   * menambah beban server yang sudah bermasalah.
   */
  get isTransient() {
    if (this.status === 507) return false;
    return this.status >= 500 || this.status === 408;
  }

  /**
   * Kuota penyimpanan habis (507).
   *
   * Dipisah dari error lain karena tindakan yang benar berbeda: mencoba
   * ulang tidak akan menolong, yang perlu dilakukan adalah menghapus dokumen
   * lama. Backend mengirim pesan yang sudah menyebut angka batas dan
   * tindakannya, jadi pesan itu yang ditampilkan apa adanya.
   */
  get isQuotaExceeded() {
    return this.status === 507;
  }
}

const FALLBACK: Record<number, string> = {
  400: "Permintaan tidak valid. Periksa kembali isian Anda.",
  401: "Sesi akses sudah berakhir. Masuk lagi untuk melanjutkan.",
  403: "Akses ditolak untuk sumber daya ini.",
  404: "Data yang Anda cari tidak ditemukan.",
  409: "Permintaan tidak bisa dijalankan sekarang. Periksa pesan di atasnya.",
  413: "Ukuran berkas melebihi batas yang diizinkan.",
  422: "Permintaan tidak dapat diproses. Periksa kembali isian Anda.",
  429: "Batas permintaan tercapai. Coba lagi sebentar lagi.",
  500: "Layanan sedang mengalami gangguan. Coba lagi sebentar lagi.",
  502: "Layanan upstream tidak merespons. Coba lagi sebentar lagi.",
  503: "Layanan sedang tidak tersedia. Coba lagi sebentar lagi.",
  504: "Permintaan terlalu lama diproses. Coba lagi sebentar lagi.",
  507: "Penyimpanan dokumen penuh. Hapus dokumen lama di halaman Dokumen.",
};

export function messageForStatus(status: number, fallback?: string) {
  return fallback ?? FALLBACK[status] ?? "Terjadi kesalahan yang tidak terduga.";
}

export function toApiError(error: unknown): ApiError {
  if (error instanceof ApiError) return error;
  if (error instanceof DOMException && error.name === "AbortError") {
    return new ApiError("Permintaan dibatalkan.", 499);
  }
  return new ApiError("Tidak dapat terhubung ke layanan.", 0);
}

export function parseErrorBody(body: unknown): ApiErrorBody | null {
  if (typeof body !== "object" || body === null) return null;
  const candidate = body as Record<string, unknown>;

  if (typeof candidate.detail === "string") {
    return {
      detail: candidate.detail,
      code: typeof candidate.code === "string" ? candidate.code : undefined,
    };
  }

  // Validasi Pydantic (422) tidak mengirim string: `detail` berupa array
  // berisi objek `{loc, msg, type}`. Tanpa penanganan ini, 422 jatuh ke
  // pesan generik padahal penyebabnya ValidatorError yang spesifik.
  if (Array.isArray(candidate.detail)) {
    const messages = candidate.detail
      .map((item) => {
        if (typeof item === "string") return item;
        if (typeof item !== "object" || item === null) return null;
        const entry = item as Record<string, unknown>;
        return typeof entry.msg === "string" ? entry.msg : null;
      })
      .filter((item): item is string => typeof item === "string");

    if (messages.length > 0) {
      return {
        detail: messages.join("; "),
        code: typeof candidate.code === "string" ? candidate.code : undefined,
      };
    }
  }

  return null;
}
