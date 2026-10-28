import type {
  Chunk,
  ChunkPage,
  Citation,
  DocumentDetail,
  DocumentPreview,
  DocumentStatus,
  DocumentSummary,
  RetrievalSettings,
  QueryLog,
} from "@/types/api";
import { extractPdfText } from "@/lib/pdf/extract-text";

/* --------------------------------------------------------------------------
   Fixture retrieval in-browser.

   Sengaja bukan data palsu yang dipretend jadi hasil produksi:
   - chunker benar-benar memecah teks yang diunggah pengguna
   - retrieval benar-benar menghitung tumpang tindih kata
   - jawaban disusun secara ekstraktif dari chunk yang benar-benar lolos
   - log query berasal dari interaksi yang benar-benar terjadi

   Kalau NEXT_PUBLIC_API_BASE_URL diisi, semua ini dilewati.
--------------------------------------------------------------------------- */

const STORAGE_KEY = "ida.mock.v1";

/** Batas dan default unggah, disamakan dengan backend. */
export const MAX_FILE_BYTES = 10 * 1024 * 1024;
export const ACCEPTED_EXTENSIONS = [".pdf", ".txt", ".md", ".markdown"] as const;
export const CHUNK_SIZE = 500;
export const CHUNK_OVERLAP = 50;

/** Batas panjang judul sesi, dipakai UI untuk validasi dan memotong. */
export const SESSION_TITLE_MAX_LENGTH = 80;

/**
 * Parameter retrieval untuk mode fixture.
 *
 * **Nilai ini sengaja berbeda dari backend** (0.82). Alasannya bukan
 * ketidaktelitian, tapi karena skalanya memang berbeda:
 *
 * - Fixture: `scoreChunk` mengembalikan cakupan token pertanyaan yang
 *   ditemukan di sebuah chunk, jadi skornya 0..1 di mana 1.0 berarti semua
 *   token pertanyaan ada di chunk itu. Pertanyaan panjang yang jawabannya ada
 *   tetap jarang melewati 0.70: kata kerja seperti "memverifikasi" sering
 *   tidak muncul di chunk yang memuat jawabannya. Ambang yang berlaku di
 *   skala ini adalah 0.20-0.60, dan sebuah chunk baru dianggap sumber bila
 *   minimal dua kata pertanyaan cocok.
 * - Backend: ambang diterapkan pada cosine similarity vektor, yang angkanya
 *   memang lebih tinggi dan dikalibrasi pada 0.75-0.92.
 *
 * Menyamakan kedua angka hanya membuat demo menolak pertanyaan yang
 * sebenarnya terjawab oleh dokumen contoh.
 */
export const DEFAULT_SETTINGS: RetrievalSettings = {
  top_k: 5,
  // Rentang demo 0.20-0.60, default 0.25. Pencocokan kata memberi skor lebih
  // rendah daripada cosine, dan cakupan kata turun drastis pada pertanyaan
  // panjang, jadi ambang tinggi menolak pertanyaan yang sebenarnya terjawab.
  // Karena itu syarat skor dilengkapi syarat minimal dua kata cocok: satu kata
  // yang kebetulan sama tidak cukup untuk dianggap sumber.
  similarity_threshold: 0.25,
};

interface StoredMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  created_at: string;
  citations: Citation[];
  not_found: boolean;
}

interface StoredSession {
  id: string;
  title: string;
  created_at: string;
  last_active_at: string;
  messages: StoredMessage[];
  /** Scope dokumen; `null` berarti sesi lintas dokumen. */
  document_id?: string | null;
}

interface StoredDocument {
  id: string;
  filename: string;
  size_bytes: number;
  page_count: number | null;
  status: DocumentStatus;
  uploaded_at: string;
  error_message: string | null;
  chunk_count: number;
  chunks: Chunk[];
  text: string;
}

interface MockState {
  documents: StoredDocument[];
  sessions: StoredSession[];
  settings: RetrievalSettings;
  logs: QueryLog[];
}

const SAMPLE_DOC_TEXT = `Standar Operasional Prosedur: Layanan Permintaan Informasi

1. Tujuan
Standar ini mengatur cara Receiving Officer menerima, memverifikasi, dan
menindaklanjuti permintaan informasi yang masuk melalui Satu Pintu Layanan.

2. Ruang Lingkup
Standar ini berlaku untuk seluruh unit kerja. Prosedur ini tidak berlaku untuk
permintaan yang berkaitan dengan data pribadi pihak ketiga yang belum
memperoleh persetujuan tertulis.

3. Definisi
3.1 Receiving Officer adalah pegawai yang ditunjuk sebagai penerima pertama
permintaan informasi.
3.2 SLA Penyelesaian adalah batas waktu maksimal penyelesaian permintaan,
yaitu dua hari kerja sejak permintaan dicatat.

4. Tanggung Jawab
4.1 Receiving Officer wajib mencatat setiap permintaan pada Sistem Tiket dalam
waktu paling lama satu jam kerja.
4.2 Kepala Unit wajib menugaskan petugas teknis yang kompeten sesuai bidang
keahlian, lalu menyatakan kesediaan kepada Receiving Officer.

5. Alur Proses
5.1 Permintaan diterima melalui formulir elektronik atau loket fisik.
5.2 Receiving Officer melakukan verifikasi kelengkapan berkas.
5.3 Bila berkas tidak lengkap, pemohon diberi pemberitahuan tertulis dalam
tempo dua hari kerja.
5.4 Berkas yang lengkap diteruskan ke unit yang diminta.
5.5 Hasil akhir disampaikan kepada pemohon dan dicatat pada Sistem Tiket.

6. Pelaporan
6.1 Laporan bulanan mencakup jumlah permintaan, waktu penyelesaian rata-rata,
dan jumlah permintaan yang tidak terlayani.
6.2 Laporan wajib disampaikan paling lambat tanggal sepuluh setiap bulan.

7. Ketentuan Lain
Permintaan yang tidak menyertakan identitas pemohon yang jelas, atau yang
berasal dari pihak ketiga tanpa persetujuan, tidak diproses.`;

const SAMPLE_TICKET_TEXT = `Panduan Penggunaan Sistem Tiket Layanan

1. Tujuan Panduan
Panduan ini menjelaskan cara membuat tiket layanan agar permintaan tercatat
rapi, terlacak, dan tidak hilang di kotak masuk surel unit kerja.

2. Sebelum Membuat Tiket
2.1 Pastikan Anda sudah masuk memakai akun dinas. Tiket yang dibuat dari akun
pribadi tidak dapat diverifikasi oleh Receiving Officer.
2.2 Siapkan nomor induk pegawai, unit kerja, dan uraian singkat kebutuhan.
2.3 Lampirkan berkas pendukung bila permintaan berkaitan dengan dokumen resmi.

3. Langkah Membuat Tiket
3.1 Langkah pertama, masuk ke menu Layanan lalu pilih Buat Tiket. Menu ini
menampilkan formulir tiket baru yang masih kosong.
3.2 Isi judul tiket dengan kalimat singkat, misalnya "Permintaan salinan
dokumen kerja sama".
3.3 Pilih kategori layanan yang paling dekat dengan kebutuhan Anda.
3.4 Tulis uraian kebutuhan secara jelas, termasuk tenggat yang diharapkan.
3.5 Unggah lampiran pendukung pada bagian Lampiran.
3.6 Periksa kembali seluruh isian, lalu tekan Kirim Tiket.
3.7 Sistem menampilkan nomor tiket. Simpan nomor itu untuk pelacakan.

4. Setelah Tiket Dikirim
4.1 Tiket berstatus Baru sampai diterima oleh Receiving Officer.
4.2 Perubahan status dapat dilihat pada menu Layanan, submenu Daftar Tiket.
4.3 Pemohon dapat menambahkan tanggapan pada tiket yang sama tanpa membuat
tiket baru.

5. Hal yang Perlu Dihindari
5.1 Membuat beberapa tiket untuk satu kebutuhan yang sama.
5.2 Menyisipkan data pribadi pihak ketiga tanpa persetujuan tertulis.
5.3 Menutup tiket sebelum hasil layanan benar-benar diterima.`;

const SAMPLE_LEAVE_TEXT = `Kebijakan Cuti Tahunan

1. Dasar Kebijakan
Kebijakan ini mengatur hak cuti tahunan pegawai, termasuk sisa cuti yang dapat
dibawa ke tahun berikutnya dan tenggat pengajuannya.

2. Hak Cuti Tahunan
2.1 Pegawai memperoleh cuti tahunan sebanyak dua belas hari kerja setiap tahun.
2.2 Cuti tahunan tidak dapat dipakai untuk menggantikan izin sakit.
2.3 Cuti tahunan diajukan melalui sistem kepegawaian paling sedikit tiga hari
kerja sebelum tanggal cuti dimulai.

3. Sisa Cuti dan Pembawaan ke Tahun Berikutnya
3.1 Sisa cuti tahunan yang tidak terpakai dapat dibawa ke tahun berikutnya
dengan batas maksimal enam hari.
3.2 Sisa cuti di atas enam hari hangus pada akhir tahun berjalan dan tidak
dapat dikonversi menjadi uang.
3.3 Cuti yang dibawa wajib dipakai paling lambat tanggal tiga puluh satu Maret
tahun berikutnya.
3.4 Sisa cuti yang belum dipakai setelah tanggal tersebut dinyatakan hangus.

4. Tenggat Pengajuan
4.1 Pengajuan cuti untuk sisa tahun sebelumnya wajib disetujui atasan langsung
paling lambat tanggal dua puluh Maret.
4.2 Pengajuan yang masuk setelah tanggal dua puluh Maret tidak diproses untuk
sisa cuti tahun sebelumnya.
4.3 Cuti tahunan berjalan tetap dapat diajukan sepanjang tahun sesuai kuota.

5. Pembatalan dan Perubahan
5.1 Pembatalan cuti yang sudah disetujui harus diajukan sebelum tanggal cuti
dimulai.
5.2 Perubahan tanggal cuti mengikuti alur persetujuan yang sama dengan
pengajuan baru.

6. Pencatatan
6.1 Saldo cuti dapat dilihat pada menu Kepegawaian, submenu Saldo Cuti.
6.2 Unit kepegawaian menutup pembukuan saldo cuti setiap tanggal tiga puluh
satu Desember.`;

function nowIso() {
  return new Date().toISOString();
}

function makeId(prefix: string) {
  const random = Math.random().toString(36).slice(2, 10);
  return `${prefix}_${random}`;
}

/* ------------------------------- chunker -------------------------------- */

/**
 * Memecah teks pada batas paragraf, lalu memotong per paragraph agar
 * ukuran chunk tidak melebihi CHUNK_SIZE. Overlap carried antar chunk supaya
 * kalimat yang melintasi batas tidak hilang utuh.
 */
export function chunkText(text: string, size = CHUNK_SIZE, overlap = CHUNK_OVERLAP): string[] {
  const normalized = text.replace(/\r\n/g, "\n").replace(/[ \t]+/g, " ").trim();
  if (normalized.length === 0) return [];

  const paragraphs = normalized.split(/\n{2,}/).map((p) => p.trim()).filter(Boolean);
  const chunks: string[] = [];
  let current = "";

  const pushCurrent = () => {
    if (current.trim().length === 0) return;
    chunks.push(current.trim());
    const tail = current.slice(Math.max(0, current.length - overlap));
    current = `${tail}\n`;
  };

  for (const paragraph of paragraphs) {
    if (paragraph.length > size) {
      pushCurrent();
      for (let start = 0; start < paragraph.length; start += size - overlap) {
        current += `${paragraph.slice(start, start + size)}\n`;
        if (current.length >= size) pushCurrent();
      }
      continue;
    }
    if (current.length + paragraph.length + 1 > size) pushCurrent();
    current += `${paragraph}\n\n`;
  }
  pushCurrent();

  return chunks.map((chunk) => chunk.replace(/\n{3,}/g, "\n\n").trim()).filter(Boolean);
}

function buildChunks(documentId: string, text: string): Chunk[] {
  return chunkText(text).map((content, index) => ({
    id: `${documentId}_c${index + 1}`,
    document_id: documentId,
    chunk_index: index,
    // Teks/TXT tidak punya nomor halaman; UI Falls back ke nomor chunk.
    page_number: null,
    content,
    token_count: Math.round(content.length / 4),
  }));
}

/**
 * Chunk untuk dokumen berhalaman (PDF).
 *
 * `chunk_index` sengaja tetap berjalan lintas halaman: UI dan sitasi memakai
 * indeks itu sebagai urutan global, sedangkan `page_number` dipakai untuk
 * melompat ke halaman asli. Halaman hasil pindai tidak menghasilkan chunk,
 * tetapi nomor halamannya tidak digeser supaya `page_number` tetap cocok
 * dengan berkas yang dibuka pengguna.
 */
function buildChunksFromPages(documentId: string, pages: string[]): Chunk[] {
  const chunks: Chunk[] = [];

  pages.forEach((pageText, pageIndex) => {
    for (const content of chunkText(pageText)) {
      const index = chunks.length;
      chunks.push({
        id: `${documentId}_c${index + 1}`,
        document_id: documentId,
        chunk_index: index,
        page_number: pageIndex + 1,
        content,
        token_count: Math.round(content.length / 4),
      });
    }
  });

  return chunks;
}

/* ---------------------------- berkas pratinjau --------------------------- */

/**
 * URL berkas asli untuk pratinjau selama tab ini hidup.
 *
 * Disimpan di memori, bukan di localStorage: object URL hanya valid untuk
 * dokumen yang membuatnya dan mati setelah muat ulang, jadi menuliskannya ke
 * storage justru menghasilkan tautan rusak. Karena itu tiap URL di-revoke
 * saat dokumennya dihapus atau fixture di-reset, supaya blob tidak menahan
 * memori sampai tab ditutup.
 */
const objectUrls = new Map<string, string>();

function registerFile(id: string, file: File) {
  if (typeof URL === "undefined" || typeof URL.createObjectURL !== "function") return;
  // Unggah ulang dengan id yang sama (mis. retry) tidak boleh menumpuk blob.
  releaseFile(id);
  objectUrls.set(id, URL.createObjectURL(file));
}

function releaseFile(id: string) {
  const url = objectUrls.get(id);
  if (!url) return;
  URL.revokeObjectURL(url);
  objectUrls.delete(id);
}

function resolveFileUrl(id: string): string | null {
  return objectUrls.get(id) ?? null;
}

/* ------------------------------- retrieval ------------------------------ */

const STOP_WORDS = new Set([
  "yang", "untuk", "dengan", "dari", "pada", "adalah", "akan", "atau", "dan",
  "itu", "ini", "apa", "bagaimana", "berapa", "di", "ke", "dalam", "oleh",
  "the", "a", "an", "of", "to", "is", "are", "in", "on", "for", "and", "or",
]);

export function tokenize(input: string): string[] {
  return input
    .toLowerCase()
    .split(/[^a-z0-9à-ÿ]+/i)
    .filter((token) => token.length > 1 && !STOP_WORDS.has(token));
}

/**
 * Skor Similarity sederhana: tumpang tindih kata kunci yang dinormalisasi
 * dengan panjang query. Cukup untuk membuktikan alur retrieval, top-k, dan
 * ambang "tidak ditemukan" berjalan di frontend.
 */
export function scoreChunk(question: string, content: string): number {
  const questionTokens = tokenize(question);
  if (questionTokens.length === 0) return 0;

  const contentTokens = new Set(tokenize(content));
  const hit = questionTokens.filter((token) => contentTokens.has(token)).length;
  return hit / questionTokens.length;
}

/**
 * Jumlah token pertanyaan yang benar-benar muncul di token chunk.
 *
 * `scoreChunk` menormalkan jumlah kata cocok dengan panjang pertanyaan,
 * sehingga pertanyaan panjang bisa berskor rendah walau chunk-nya memuat
 * jawaban. Angka absolut ini dipakai sebagai syarat tambahan: satu kata yang
 * kebetulan sama (mis. "layanan") tidak cukup untuk menyebut chunk sebagai
 * sumber, jadi sitasi tidak menunjuk ke bagian yang tidak relevan.
 */
export function countMatches(question: string, content: string): number {
  const contentTokens = new Set(tokenize(content));
  return tokenize(question).filter((token) => contentTokens.has(token)).length;
}

function extractiveAnswer(
  question: string,
  top: Array<{ citation: Citation; content: string }>,
): string {
  const lead = top[0];
  const lines: string[] = [];

  lines.push(
    `Informasi yang paling mendekati pertanyaan Anda ditemukan di ${top.length} chunk berikut.`,
  );
  lines.push("");
  lines.push(`Chunk #${lead.citation.chunk_index + 1} dari ${lead.citation.document_name}`);
  lines.push("");
  lines.push(quoteBlock(lead.content));

  if (top.length > 1) {
    lines.push("");
    lines.push("Bagian lain yang juga relevan");
    top.slice(1).forEach((item) => {
      lines.push(
        `- ${item.citation.document_name}, chunk #${item.citation.chunk_index + 1}, `
          + `skor ${item.citation.score.toFixed(2)}`,
      );
    });
  }

  lines.push("");
  lines.push(
    "Jawaban ini disusun langsung dari kutipan chunk di atas. Backend FastAPI akan "
    + "mengganti langkah ini dengan sintesis LLM yang tetap terikat pada kutipan yang sama.",
  );

  return lines.join("\n");
}

function quoteBlock(text: string) {
  return text
    .split("\n")
    .map((line) => `> ${line}`)
    .join("\n");
}

/* -------------------------------- storage -------------------------------- */

/** Pembungkus state supaya skema fixture bisa diganti tanpa merusak cache lama. */
interface StoredEnvelope {
  version: 3;
  state: MockState;
}

function seedState(): MockState {
  /**
   * Tiga dokumen contoh siap pakai, bukan satu.
   *
   * Satu dokumen saja membuat pertanyaan lintas topik selalu jatuh ke
   * "tidak ditemukan", sehingga mode demo tidak bisa memperlihatkan pemilihan
   * sumber maupun sitasi dari beberapa berkas. Karena itu tiap contoh mewakili
   * topik yang berbeda (prosedur, tiket, kepegawaian) dan tanggal unggahnya
   * sengaja dibuat berbeda beberapa jam agar urutan daftar terlihat wajar.
   */
  const seedDocument = (
    id: string,
    filename: string,
    text: string,
    hoursAgo: number,
  ): StoredDocument => {
    const chunks = buildChunks(id, text);
    return {
      id,
      filename,
      size_bytes: new Blob([text]).size,
      page_count: null,
      status: "ready",
      uploaded_at: new Date(Date.now() - 1000 * 60 * 60 * hoursAgo).toISOString(),
      error_message: null,
      chunk_count: chunks.length,
      chunks,
      text,
    };
  };

  return {
    documents: [
      seedDocument("doc_sample_sop", "contoh-sop-layanan.md", SAMPLE_DOC_TEXT, 5),
      seedDocument("doc_sample_tiket", "panduan-tiket-layanan.md", SAMPLE_TICKET_TEXT, 9),
      seedDocument("doc_sample_cuti", "kebijakan-cuti.md", SAMPLE_LEAVE_TEXT, 14),
    ],
    sessions: [],
    settings: { ...DEFAULT_SETTINGS },
    logs: [],
  };
}

let cache: MockState | null = null;

function read(): MockState {
  if (cache) return cache;

  if (typeof window === "undefined") {
    cache = seedState();
    return cache;
  }

  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (raw) {
      const envelope = JSON.parse(raw) as Partial<StoredEnvelope>;
      // Ganti skema lama supaya seed baru tidak bentrok dengan cache lama.
      // Skema 3 mengganti ambang tersimpan: sebelum ini pengunjung bisa
      // menyimpan 0.82, angka skala cosine yang membuat mode demo menolak
      // pertanyaan yang jawabannya ada.
      if (envelope?.version === 3 && envelope.state) {
        cache = envelope.state as MockState;
        return cache;
      }
    }
  } catch {
    // localStorage bisa diblokir atau isinya rusak; fixture in-memory tetap jalan.
  }

  cache = seedState();
  persist();
  return cache;
}

function persist() {
  if (typeof window === "undefined" || !cache) return;
  try {
    const envelope: StoredEnvelope = { version: 3, state: cache };
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(envelope));
  } catch {
    // Kuota penuh atau storage diblokir: biarkan state in-memory saja.
  }
}

function commit() {
  persist();
}

function toSummary(doc: StoredDocument): DocumentSummary {
  return {
    id: doc.id,
    filename: doc.filename,
    page_count: doc.page_count,
    size_bytes: doc.size_bytes,
    status: doc.status,
    uploaded_at: doc.uploaded_at,
    error_message: doc.error_message,
    chunk_count: doc.chunk_count,
  };
}

/* --------------------------------- API ----------------------------------- */

/** Jeda pendek supaya status ingestion terlihat (dan tidak terasa instan). */
function sleep(ms: number) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

export const mockApi = {
  async listDocuments(): Promise<DocumentSummary[]> {
    await sleep(180);
    return read()
      .documents.map(toSummary)
      .sort((a, b) => b.uploaded_at.localeCompare(a.uploaded_at));
  },

  async getDocument(id: string): Promise<DocumentDetail> {
    await sleep(200);
    const doc = read().documents.find((item) => item.id === id);
    // Backend membalas 404, jadi mock harus berperilaku sama.
    // Mengembalikan `null` membuat halaman detail merender layar kosong
    // alih-alih "dokumen tidak ditemukan" saat tautannya rusak.
    if (!doc) throw Object.assign(new Error("Dokumen tidak ditemukan."), { status: 404 });
    // Sengaja tanpa `chunks`: daftar chunk diambil terpisah supaya dokumen
    // besar tidak mengirim seluruh isinya sekaligus.
    return {
      ...toSummary(doc),
      ingestion: {
        splitter: "RecursiveCharacterTextSplitter",
        chunk_size: CHUNK_SIZE,
        chunk_overlap: CHUNK_OVERLAP,
        embedding_model: "fixture lokal (tanpa embedding)",
        vector_store: "fixture lokal (tanpa vector store)",
      },
    };
  },

  async getDocumentChunks(
    id: string,
    { page, pageSize, search }: { page: number; pageSize: number; search?: string },
  ): Promise<ChunkPage> {
    await sleep(160);
    const doc = read().documents.find((item) => item.id === id);
    if (!doc) return { items: [], total: 0, page, page_size: pageSize };

    const term = search?.trim().toLowerCase() ?? "";
    const matched =
      term.length === 0
        ? doc.chunks
        : doc.chunks.filter((chunk) => chunk.content.toLowerCase().includes(term));

    const start = (page - 1) * pageSize;
    return {
      items: matched.slice(start, start + pageSize),
      total: matched.length,
      page,
      page_size: pageSize,
    };
  },

  /**
   * Pratinjau isi dokumen untuk fixture.
   *
   * Bentuknya sengaja sama dengan backend: teks hasil parsing, disusun
   * berurutan, dengan penanda `truncated`. Mode demo dan mode backend harus
   * berperilaku sama, termasuk pada halaman ini.
   */
  async getDocumentPreview(id: string): Promise<DocumentPreview> {
    await sleep(200);
    const doc = read().documents.find((item) => item.id === id);
    if (!doc) {
      throw Object.assign(new Error("Dokumen tidak ditemukan."), { status: 404 });
    }

    const ordered = [...doc.chunks].sort(
      (left, right) => left.chunk_index - right.chunk_index,
    );
    const content = ordered.map((chunk) => chunk.content).join("\n\n");
    if (ordered.length === 0) {
      throw Object.assign(
        new Error(
          "Dokumen ini belum punya isi yang bisa ditampilkan. "
          + "Tunggu sampai ingestion selesai, atau periksa statusnya.",
        ),
        { status: 409 },
      );
    }

    return {
      id: doc.id,
      filename: doc.filename,
      status: doc.status,
      content,
      chunk_count: doc.chunk_count,
      truncated: false,
      preview_chars: content.length,
      total_chars: content.length,
    };
  },

  /**
   * Unggah berkas di mode fixture.
   *
   * PDF benar-benar diparse di browser lewat PDF.js, jadi alur "berhasil",
   * "tidak ada teks (hasil pindai)", dan "berkas rusak" bisa dicoba tanpa
   * backend. Dokumen dikembalikan dalam status `processing` lebih dulu, sama
   * seperti unggahan ke backend yang baru selesai saat worker selesai.
   */
  async uploadDocument(file: File): Promise<DocumentSummary> {
    const state = read();
    const lower = file.name.toLowerCase();
    const isPdf = lower.endsWith(".pdf");
    const isText = ACCEPTED_EXTENSIONS.some((ext) => lower.endsWith(ext));

    if (file.size > MAX_FILE_BYTES) {
      throw Object.assign(new Error("Berkas melebihi batas 10 MB."), { status: 413 });
    }
    if (!isPdf && !isText) {
      throw Object.assign(new Error("Format tidak didukung. Gunakan PDF, TXT, atau Markdown."), {
        status: 400,
      });
    }

    const id = makeId("doc");
    const uploaded_at = nowIso();

    // Berkas asli disimpan supaya pratinjau bisa menampilkan dokumen yang
    // sebenarnya, bukan hanya teks hasil parsing.
    registerFile(id, file);

    if (isPdf) {
      state.documents.unshift({
        id,
        filename: file.name,
        size_bytes: file.size,
        page_count: null,
        status: "processing",
        uploaded_at,
        error_message: null,
        chunk_count: 0,
        chunks: [],
        text: "",
      });
      commit();

      void (async () => {
        try {
          const { pages, pageCount } = await extractPdfText(file);
          // Dokumen bisa saja sudah dihapus saat ekstraksi berjalan.
          const doc = state.documents.find((item) => item.id === id);
          if (!doc) return;

          const chunks = buildChunksFromPages(id, pages);
          doc.page_count = pageCount;
          doc.text = pages.join("\n\n");

          if (chunks.length === 0) {
            doc.status = "failed";
            doc.error_message =
              "Tidak ada teks yang bisa dibaca dari PDF ini. "
              + "Berkas hasil pindai perlu OCR sebelum diunggah.";
          } else {
            doc.chunks = chunks;
            doc.chunk_count = chunks.length;
            doc.status = "ready";
            doc.error_message = null;
          }
          commit();
        } catch (error) {
          const doc = state.documents.find((item) => item.id === id);
          if (!doc) return;
          doc.status = "failed";
          // Pesan dari extractPdfText sudah user-facing (rusak/terkunci),
          // jadi diteruskan apa adanya alih-alih ditelan jadi pesan generik.
          doc.error_message = error instanceof Error && error.message
            ? error.message
            : "PDF gagal diproses.";
          commit();
        }
      })();

      return toSummary(state.documents.find((item) => item.id === id)!);
    }

    const text = await file.text();

    state.documents.unshift({
      id,
      filename: file.name,
      size_bytes: file.size,
      page_count: 0,
      status: "processing",
      uploaded_at,
      error_message: null,
      chunk_count: 0,
      chunks: [],
      text,
    });
    commit();

    // Simulasi worker ingestion: beberapa detik lalu status naik ke ready.
    void (async () => {
      await sleep(2600);
      const doc = state.documents.find((item) => item.id === id);
      if (!doc) return;
      doc.chunks = buildChunks(id, doc.text);
      doc.chunk_count = doc.chunks.length;
      doc.page_count = 0;
      doc.status = doc.chunks.length > 0 ? "ready" : "failed";
      doc.error_message = doc.chunks.length > 0
        ? null
        : "Tidak ada teks yang bisa dibaca dari berkas ini.";
      commit();
    })();

    return toSummary(state.documents.find((item) => item.id === id)!);
  },

  async deleteDocument(id: string): Promise<void> {
    await sleep(150);
    const state = read();
    state.documents = state.documents.filter((doc) => doc.id !== id);
    // Blob pratinjau ikut dilepas, kalau tidak memori tab menahan berkas
    // yang sudah tidak bisa diakses dari UI.
    releaseFile(id);
    for (const session of state.sessions) {
      const remaining = session.messages.filter((message) =>
        message.citations.every((citation) => citation.document_id !== id),
      );
      for (const message of remaining) {
        message.citations = message.citations.filter((c) => c.document_id !== id);
      }
      session.messages = remaining;
    }
    commit();
  },

  /**
   * URL berkas asli untuk pratinjau (`<iframe>`/`<embed>`).
   * `null` berarti berkas tidak tersedia di sesi ini — misalnya dokumen
   * contoh bawaan, dokumen lama dari localStorage, atau setelah muat ulang.
   */
  getFileUrl(id: string): string | null {
    return resolveFileUrl(id);
  },

  async listSessions() {
    await sleep(160);
    return read()
      .sessions.map((session) => ({
        id: session.id,
        title: session.title,
        created_at: session.created_at,
        last_active_at: session.last_active_at,
        message_count: session.messages.length,
        document_id: session.document_id ?? null,
      }))
      .sort((a, b) => b.last_active_at.localeCompare(a.last_active_at));
  },

  async getHistory(sessionId: string) {
    await sleep(160);
    const session = read().sessions.find((item) => item.id === sessionId);
    if (!session) return null;
    return {
      session: {
        id: session.id,
        title: session.title,
        created_at: session.created_at,
        last_active_at: session.last_active_at,
        message_count: session.messages.length,
        document_id: session.document_id ?? null,
      },
      messages: session.messages,
    };
  },

  createSessionId() {
    return makeId("ses");
  },

  titleFrom(question: string) {
    const trimmed = question.trim().replace(/\s+/g, " ");
    return trimmed.length > 60 ? `${trimmed.slice(0, 60)}...` : trimmed;
  },

  appendMessage(
    sessionId: string,
    message: Omit<StoredMessage, "id" | "created_at">,
    documentId?: string | null,
  ) {
    const state = read();
    let session = state.sessions.find((item) => item.id === sessionId);
    if (!session) {
      session = {
        id: sessionId,
        title: message.role === "user" ? this.titleFrom(message.content) : "Percakapan baru",
        created_at: nowIso(),
        last_active_at: nowIso(),
        messages: [],
        document_id: documentId ?? null,
      };
      state.sessions.push(session);
    }
    session.messages.push({ ...message, id: makeId("msg"), created_at: nowIso() });
    session.last_active_at = nowIso();
    commit();
    return session;
  },

  /**
   * Judul sesi hanya diisi sekali, saat pesan pertama datang. Setelah itu
   * `title` adalah milik pengguna, dan pesan berikutnya tidak menimpanya.
   */
  async renameSession(id: string, title: string) {
    await sleep(140);
    const session = read().sessions.find((item) => item.id === id);
    if (!session) {
      throw Object.assign(new Error("Sesi tidak ditemukan."), { status: 404 });
    }
    const trimmed = title.trim().replace(/\s+/g, " ");
    if (trimmed.length === 0) {
      throw Object.assign(new Error("Nama sesi tidak boleh kosong."), { status: 400 });
    }
    session.title = trimmed.slice(0, SESSION_TITLE_MAX_LENGTH);
    commit();
  },

  async deleteSession(id: string) {
    await sleep(140);
    const state = read();
    const before = state.sessions.length;
    state.sessions = state.sessions.filter((item) => item.id !== id);
    if (state.sessions.length === before) {
      throw Object.assign(new Error("Sesi tidak ditemukan."), { status: 404 });
    }
    commit();
  },

  async resetSessions() {
    await sleep(150);
    const state = read();
    state.sessions = [];
    commit();
  },

  async getSettings(): Promise<RetrievalSettings> {
    await sleep(120);
    return { ...read().settings };
  },

  async updateSettings(patch: Partial<RetrievalSettings>): Promise<RetrievalSettings> {
    await sleep(140);
    const state = read();
    state.settings = { ...state.settings, ...patch };
    commit();
    return { ...state.settings };
  },

  async recordLog(log: QueryLog) {
    const state = read();
    state.logs.unshift(log);
    // Fixture lokal tidak butuh riwayat tanpa batas.
    state.logs = state.logs.slice(0, 200);
    commit();
  },
  /** Jawaban yang akan di-stream, plus sitasi yang menyertainya. */
  compose(question: string, documentId?: string | null) {
    const state = read();
    const settings = state.settings;
    // Scope dokumen: chat privat hanya mencari di dokumen itu, sama seperti
    // filter `document_ids` di backend.
    const ready = state.documents.filter(
      (doc) => doc.status === "ready" && (!documentId || doc.id === documentId),
    );

    const ranked = ready
      .flatMap((doc) =>
        doc.chunks.map((chunk) => ({
          citation: {
            document_id: doc.id,
            document_name: doc.filename,
            page_number: chunk.page_number,
            chunk_index: chunk.chunk_index,
            excerpt: chunk.content.slice(0, 220),
            score: scoreChunk(question, chunk.content),
          } satisfies Citation,
          content: chunk.content,
        })),
      )
      // Dua syarat sekaligus: skor cakupan kata di atas ambang, DAN minimal
      // dua kata pertanyaan benar-benar ada di chunk. Skor cakupan turun
      // drastis pada pertanyaan panjang, sementara satu kata yang kebetulan
      // sama tidak cukup untuk dianggap sumber — tanpa syarat kedua, sitasi
      // bisa menunjuk ke chunk yang tidak relevan.
      .filter(
        (item) =>
          item.citation.score >= settings.similarity_threshold
          && countMatches(question, item.content) >= 2,
      )
      .sort((a, b) => b.citation.score - a.citation.score)
      .slice(0, settings.top_k);

    if (ranked.length === 0) {
      return { notFound: true as const, text: "", citations: [] as Citation[] };
    }

    return {
      notFound: false as const,
      text: extractiveAnswer(question, ranked),
      citations: ranked.map((item) => item.citation),
    };
  },

  analyticsSummary() {
    const state = read();
    const byDay = new Map<string, { durations: number[] }>();

    for (const log of state.logs) {
      const day = log.created_at.slice(0, 10);
      const bucket = byDay.get(day) ?? { durations: [] };
      bucket.durations.push(log.response_time_ms);
      byDay.set(day, bucket);
    }

    const days = [...byDay.keys()].sort().slice(-14);
    const latency = days.map((day) => {
      const durations = byDay.get(day)!.durations;
      const avg = durations.reduce((sum, value) => sum + value, 0) / durations.length;
      const sorted = [...durations].sort((a, b) => a - b);
      const p95 = sorted[Math.min(sorted.length - 1, Math.floor(sorted.length * 0.95))] ?? 0;
      return { date: day, avg_ms: Math.round(avg), p95_ms: p95 };
    });
    // Token usage dihitung dari perkiraan panjang prompt, bukan tagihan asli.
    const tokens = days.map((day) => {
      const dayLogs = state.logs.filter((log) => log.created_at.slice(0, 10) === day);
      const input = dayLogs.reduce(
        (sum, log) => sum + Math.ceil((log.question.length + 2000) / 4),
        0,
      );
      const output = dayLogs.reduce(
        (sum, log) => sum + Math.ceil((log.sources_count * 480 + 180) / 4),
        0,
      );
      return { date: day, input_tokens: input, output_tokens: output };
    });

    return {
      // Belum pernah ada evaluasi RAGAS di mode fixture. Halaman analitik
      // menampilkan empty state, bukan angka contoh.
      latest_eval: null,
      latency,
      tokens,
    };
  },

  analyticsLogs(page: number, pageSize: number) {
    const state = read();
    const start = (page - 1) * pageSize;
    return {
      items: state.logs.slice(start, start + pageSize),
      total: state.logs.length,
      page,
      page_size: pageSize,
    };
  },

  reset() {
    // Fixture dikembalikan ke seed, jadi semua berkas unggahan (beserta blob
    // pratinjaunya) memang dibuang. Salin key dulu karena releaseFile
    // menghapus entri map saat diiterasi.
    [...objectUrls.keys()].forEach(releaseFile);
    cache = seedState();
    commit();
  },
};

export type MockApi = typeof mockApi;
