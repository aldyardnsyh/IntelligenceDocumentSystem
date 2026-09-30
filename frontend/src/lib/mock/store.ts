import type {
  Chunk,
  ChunkPage,
  Citation,
  DocumentDetail,
  DocumentStatus,
  DocumentSummary,
  RetrievalSettings,
  QueryLog,
} from "@/types/api";

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

/** Batas dan default PRD FR-1.1 / FR-1.2. */
export const MAX_FILE_BYTES = 10 * 1024 * 1024;
export const ACCEPTED_EXTENSIONS = [".pdf", ".txt", ".md", ".markdown"] as const;
export const CHUNK_SIZE = 500;
export const CHUNK_OVERLAP = 50;

/** Batas panjang judul sesi, dipakai UI untuk validasi dan memotong. */
export const SESSION_TITLE_MAX_LENGTH = 80;

/**
 * Parameter retrieval untuk mode mock.
 *
 * **Nilai ini sengaja berbeda dari backend** (0.5). Alasannya bukan
 * ketidaktelitian, tapi karena skalanya memang berbeda:
 *
 * - Mock: `scoreChunk` mengembalikan cakupan token pertanyaan yang ditemukan,
 *   jadi skornya 0..1 di mana 1.0 berarti semua token pertanyaan ada.
 *   Ambang 0.5 di sini akan menolak pertanyaan panjang yang jawabannya ada:
 *   "memverifikasi kelengkapan berkas" hanya menghasilkan 0.67, karena
 *   kata kerja itu tidak muncul di chunk yang sama.
 * - Backend: ambang diterapkan pada bukti mentah (cosine similarity vektor
 *   atau skor BM25 ternormalisasi), yang angkanya memang lebih tinggi.
 *
 * Begitu backend terhubung, nilai mock ini tidak lagi dipakai: `getSettings`
 * membaca dari server. Yang penting sekarang adalah tidak menyamakan dua
 * angka yang berbeda makna hanya agar terlihat rapi.
 */
export const DEFAULT_SETTINGS: RetrievalSettings = {
  top_k: 5,
  similarity_threshold: 0.35,
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
    // Teks/TXT tidak punya nomor halaman; UI Falls back ke nomor chunk (FR-2.2).
    page_number: null,
    content,
    token_count: Math.round(content.length / 4),
  }));
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
  version: 2;
  state: MockState;
}

function seedState(): MockState {
  const uploadedAt = new Date(Date.now() - 1000 * 60 * 60 * 5).toISOString();
  const id = "doc_sample_sop";
  const chunks = buildChunks(id, SAMPLE_DOC_TEXT);

  return {
    documents: [
      {
        id,
        filename: "contoh-sop-layanan.md",
        size_bytes: new Blob([SAMPLE_DOC_TEXT]).size,
        page_count: null,
        status: "ready",
        uploaded_at: uploadedAt,
        error_message: null,
        chunk_count: chunks.length,
        chunks,
        text: SAMPLE_DOC_TEXT,
      },
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
      if (envelope?.version === 2 && envelope.state) {
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
    const envelope: StoredEnvelope = { version: 2, state: cache };
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

  async getDocument(id: string): Promise<DocumentDetail | null> {
    await sleep(200);
    const doc = read().documents.find((item) => item.id === id);
    if (!doc) return null;
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
   * File PDF tidak bisa diparse di browser, jadi fixture menandainya gagal
   * dengan pesan yang persis seperti yang akan diberikan backend, supaya alur
   * "gagal diproses" bisa dicoba tanpa backend.
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
    const text = isText ? await file.text() : "";

    state.documents.unshift({
      id,
      filename: file.name,
      size_bytes: file.size,
      page_count: isPdf ? null : 0,
      status: isPdf ? "failed" : "processing",
      uploaded_at,
      error_message: isPdf
        ? "Ekstraksi teks PDF dijalankan di server. Hubungkan backend FastAPI untuk mengunggah PDF."
        : null,
      chunk_count: 0,
      chunks: [],
      text,
    });
    commit();

    if (!isPdf) {
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
    }

    return toSummary(state.documents.find((item) => item.id === id)!);
  },

  async deleteDocument(id: string): Promise<void> {
    await sleep(150);
    const state = read();
    state.documents = state.documents.filter((doc) => doc.id !== id);
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

  async listSessions() {
    await sleep(160);
    return read()
      .sessions.map((session) => ({
        id: session.id,
        title: session.title,
        created_at: session.created_at,
        last_active_at: session.last_active_at,
        message_count: session.messages.length,
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

  appendMessage(sessionId: string, message: Omit<StoredMessage, "id" | "created_at">) {
    const state = read();
    let session = state.sessions.find((item) => item.id === sessionId);
    if (!session) {
      session = {
        id: sessionId,
        title: message.role === "user" ? this.titleFrom(message.content) : "Percakapan baru",
        created_at: nowIso(),
        last_active_at: nowIso(),
        messages: [],
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
  compose(question: string) {
    const state = read();
    const settings = state.settings;
    const ready = state.documents.filter((doc) => doc.status === "ready");

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
      .filter((item) => item.citation.score >= settings.similarity_threshold)
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
    cache = seedState();
    commit();
  },
};

export type MockApi = typeof mockApi;
