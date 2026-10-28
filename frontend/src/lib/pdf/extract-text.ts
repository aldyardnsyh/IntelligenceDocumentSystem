/**
 * Ekstraksi teks PDF di browser memakai PDF.js.
 *
 * PDF.js membagi pekerjaan menjadi dua: kode utama dan worker. Worker dimuat
 * lewat URL, bukan bundler, dan URL-nya harus menunjuk berkas yang benar-benar
 * ada saat runtime. Karena itu worker disalin ke `public/pdf.worker.min.mjs`
 * oleh `scripts/copy-pdf-worker.mjs` (dipanggil lewat `predev` dan `prebuild`).
 * Menunjuk `import.meta.url` atau membiarkan bundler menebak path tidak aman di
 * sini: webpack dan Turbopack memperlakukan aset worker dengan cara berbeda,
 * dan salah satunya akan menghasilkan 404 di produksi.
 *
 * PDF.js diimpor secara dinamis supaya bundel halaman yang tidak memakai
 * ekstraksi PDF tidak ikut membawa library sebesar ini.
 */

export type ExtractedPdfText = {
  /** Teks per halaman. Halaman tanpa teks tetap ada sebagai string kosong. */
  pages: string[];
  pageCount: number;
};

const WORKER_SRC = "/pdf.worker.min.mjs";

const UNREADABLE_MESSAGE =
  "Dokumen PDF tidak bisa dibaca. Berkas mungkin dikunci kata sandi atau rusak.";

/** Hapus spasi ganda, baris baru, dan spasi di ujung. */
function tidy(raw: string): string {
  return raw.replace(/\s+/g, " ").trim();
}

/** PDF.js melempar error bernama untuk berkas rusak atau terkunci. */
function isUnreadablePdf(error: unknown): boolean {
  if (!(error instanceof Error)) return false;
  return (
    error.name === "PasswordException" ||
    error.name === "InvalidPDFException" ||
    error.name === "MissingPDFException" ||
    error.name === "FormatError"
  );
}

export async function extractPdfText(file: File): Promise<ExtractedPdfText> {
  const pdfjs = await import("pdfjs-dist");
  pdfjs.GlobalWorkerOptions.workerSrc = WORKER_SRC;

  const data = new Uint8Array(await file.arrayBuffer());
  const task = pdfjs.getDocument({ data });

  try {
    const pdf = await task.promise;

    const pages: string[] = [];
    for (let pageNumber = 1; pageNumber <= pdf.numPages; pageNumber += 1) {
      const page = await pdf.getPage(pageNumber);
      const content = await page.getTextContent();
      const text = content.items
        .map((item) => ("str" in item ? item.str : ""))
        .join(" ");

      // Halaman hasil scan tidak punya teks, tetapi entrinya tetap disimpan
      // supaya nomor halaman tidak bergeser terhadap dokumen asli.
      pages.push(tidy(text));
      page.cleanup();
    }

    return { pages, pageCount: pdf.numPages };
  } catch (error) {
    if (isUnreadablePdf(error)) {
      throw new Error(UNREADABLE_MESSAGE, { cause: error });
    }
    throw error;
  } finally {
    // Loading task memiliki `destroy()` dan ikut membersihkan dokumen yang
    // dihasilkannya, termasuk saat pemuatan gagal sebelum dokumen terbentuk.
    await task.destroy();
  }
}