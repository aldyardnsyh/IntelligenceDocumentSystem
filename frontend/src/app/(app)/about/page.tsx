import type { Metadata } from "next";
import Link from "next/link";
import {
  ArrowUpRight,
  Boxes,
  Database,
  FileSearch,
  History,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { LinkButton } from "@/components/common/link-button";
import { externalLinks } from "@/lib/api/config";

export const metadata: Metadata = {
  title: "Tentang & Arsitektur",
  description: "Cara kerja pipeline RAG dan tumpukan teknologi yang dipakai.",
};

const PIPELINE = [
  {
    Icon: Boxes,
    phase: "Tahap 01",
    title: "Ingestion dokumen",
    body: "Berkas PDF, TXT, atau Markdown diekstrak teksnya, dibersihkan dari whitespace berlebih, lalu dipecah dengan RecursiveCharacterTextSplitter. Setiap chunk menyimpan document_id, chunk_index, dan nomor halaman bila tersedia.",
  },
  {
    Icon: Database,
    phase: "Tahap 02",
    title: "Vektorisasi dan indeks",
    body: "Tiap chunk di-embed dan disimpan beserta metadatanya di vector store. Metadata dokumen disimpan terpisah di basis data relasional, sehingga daftar dokumen bisa difilter tanpa menyentuh indeks vektor.",
  },
  {
    Icon: FileSearch,
    phase: "Tahap 03",
    title: "Retrieval berbasis kemiripan",
    body: "Pertanyaan diubah menjadi vektor lalu dicocokkan dengan cosine similarity. Ambang kemiripan menentukan apakah sebuah chunk dianggap relevan. Kalau tidak ada yang melewati ambang, sistem bilang tidak ditemukan, bukan menebak.",
  },
  {
    Icon: History,
    phase: "Tahap 04",
    title: "Generation dan memori percakapan",
    body: "Chunk yang lolos dikirim ke LLM bersama riwayat percakapan sesi. Jawaban di-stream per token, dan setiap jawaban menyertakan daftar sumber yang bisa ditelusuri ke chunk aslinya.",
  },
] as const;

const STACK = [
  { name: "Next.js", detail: "App Router dan streaming UI" },
  { name: "TypeScript", detail: "Kontrak API bertipe penuh" },
  { name: "Tailwind CSS", detail: "Token desain sebagai utilitas" },
  { name: "shadcn/ui", detail: "Primitif aksesibel, disalin ke repo" },
  { name: "TanStack Query", detail: "Cache dan polling status ingestion" },
  { name: "Recharts", detail: "Grafik latensi dan konsumsi token" },
  { name: "FastAPI", detail: "Backend, SSE, auto-dokumentasi OpenAPI" },
  { name: "LangChain", detail: "Orkestrasi pipeline RAG" },
  { name: "ChromaDB", detail: "Penyimpanan vektor" },
  { name: "sentence-transformers", detail: "Embedding lokal all-MiniLM-L6-v2" },
  { name: "Groq", detail: "Inferensi LLM latensi rendah" },
  { name: "Redis (Upstash)", detail: "Memori sesi dan cache query" },
  { name: "Supabase", detail: "Metadata dokumen dan log" },
  { name: "Langfuse", detail: "Tracing tiap panggilan LLM" },
  { name: "RAGAS", detail: "Evaluasi kualitas retrieval dan jawaban" },
] as const;

const MISSING_LINKS = [
  { href: externalLinks.repository, envName: "NEXT_PUBLIC_REPO_URL", label: "Repository GitHub" },
  { href: externalLinks.apiDocs, envName: "NEXT_PUBLIC_API_DOCS_URL", label: "Dokumentasi API" },
] as const;

const missingEnvNames = MISSING_LINKS.filter((item) => item.href === null).map((item) => item.envName);

/**
 * Tautan keluar selalu punya dua tampilan: tautan nyata kalau env-nya diisi,
 * dan tombol nonaktif berlabel kalau belum. Tidak pernah menautkan ke halaman
 * yang tidak ada.
 */
function ExternalLinkButton({
  href,
  envName,
  label,
}: {
  href: string | null;
  envName: string;
  label: string;
}) {
  if (href) {
    return (
      <LinkButton
        variant="secondary"
        href={href}
        target="_blank"
        rel="noreferrer"
        className="gap-1.5"
      >
        {label}
        <ArrowUpRight className="size-3.5" aria-hidden />
      </LinkButton>
    );
  }

  return (
    <Button
      variant="secondary"
      disabled
      title={`Isi ${envName} untuk mengaktifkan tautan ini`}
      className="gap-1.5"
    >
      {label}
      <span className="text-[10px] opacity-80">belum diatur</span>
    </Button>
  );
}

export default function AboutPage() {
  return (
    <div className="mx-auto flex w-full max-w-[860px] flex-1 flex-col gap-14 px-4 py-10 sm:px-6">
      <header className="flex flex-col gap-3">
        <p className="eyebrow">Arsitektur sistem</p>
        <h1 className="text-3xl font-semibold tracking-tight">Tentang &amp; Arsitektur</h1>
        <p className="max-w-2xl text-[15px] leading-relaxed text-muted-foreground">
          Aplikasi tanya-jawab berbasis dokumen. Prinsip desainnya satu: jawaban
          harus bisa ditelusuri balik ke sumbernya, dan ketika sumbernya tidak
          ada, sistem mengatakannya.
        </p>
      </header>

      <section className="flex flex-col gap-5">
        <h2 className="text-xl font-semibold tracking-tight">Alur kerja</h2>
        {/*
          Empat tahap disusun vertikal dengan garis penghubung di kiri, bukan
          grid empat kartu. Urutannya adalah informasi utamanya, jadi bentuknya mengikuti urutan, bukan kolom.
        */}
        <ol className="relative flex flex-col gap-6 border-l border-border pl-6">
          {PIPELINE.map(({ Icon, phase, title, body }) => (
            <li key={phase} className="relative flex flex-col gap-2">
              <span
                className="absolute -left-[31px] top-0.5 flex size-5 items-center justify-center rounded-full bg-card ring-1 ring-border"
                aria-hidden
              >
                <Icon className="size-3 text-primary" />
              </span>
              <span className="font-mono text-[11px] text-muted-foreground">{phase}</span>
              <h3 className="text-[15px] font-semibold">{title}</h3>
              <p className="text-[13px] leading-relaxed text-muted-foreground">{body}</p>
            </li>
          ))}
        </ol>
      </section>

      <section className="flex flex-col gap-4">
        <h2 className="text-xl font-semibold tracking-tight">Pencegahan jawaban mengada-ada</h2>
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <div className="flex flex-col gap-2 rounded-lg bg-card p-5 ring-1 ring-border">
            <h3 className="text-[14px] font-semibold">Ambang kemiripan</h3>
            <p className="text-[13px] leading-relaxed text-muted-foreground">
              Kalau skor chunk teratas masih di bawah ambang, pipeline berhenti
              sebelum memanggil LLM. Tidak ada panggilan model yang bisa
              mengarang jawaban dari konteks kosong.
            </p>
          </div>
          <div className="flex flex-col gap-2 rounded-lg bg-card p-5 ring-1 ring-border">
            <h3 className="text-[14px] font-semibold">Sitasi yang bisa ditelusuri</h3>
            <p className="text-[13px] leading-relaxed text-muted-foreground">
              Setiap sumber pada jawaban tertaut ke halaman detail dokumen, di
              mana chunk asal bisa dibaca langsung. Verifikasi tidak berhenti di
              klaim.
            </p>
          </div>
        </div>
      </section>

      <section className="flex flex-col gap-4">
        <h2 className="text-xl font-semibold tracking-tight">Tumpukan teknologi</h2>
        <ul className="grid grid-cols-1 gap-px overflow-hidden rounded-lg bg-border ring-1 ring-border sm:grid-cols-2 lg:grid-cols-3">
          {STACK.map((item) => (
            <li key={item.name} className="flex flex-col gap-0.5 bg-card px-4 py-3">
              <span className="text-[13px] font-medium">{item.name}</span>
              <span className="text-[12px] leading-snug text-muted-foreground">{item.detail}</span>
            </li>
          ))}
        </ul>
      </section>

      <section className="flex flex-col gap-4 rounded-lg bg-primary p-6 text-primary-foreground">
        <h2 className="text-lg font-semibold">Ingin lihat implementasinya?</h2>
        <p className="max-w-xl text-[13px] leading-relaxed text-primary-foreground/80">
          Kode sumber dan spesifikasi OpenAPI tersedia untuk ditinjau.
        </p>
        <div className="flex flex-wrap gap-2">
          <ExternalLinkButton
            href={externalLinks.repository}
            envName="NEXT_PUBLIC_REPO_URL"
            label="Repository GitHub"
          />
          <ExternalLinkButton
            href={externalLinks.apiDocs}
            envName="NEXT_PUBLIC_API_DOCS_URL"
            label="Dokumentasi API"
          />
        </div>
        {missingEnvNames.length > 0 ? (
          <p className="text-[12px] leading-relaxed text-primary-foreground/70">
            Belum semua tautan aktif. Isi{" "}
            {missingEnvNames.map((name, index) => (
              <span key={name}>
                {index > 0 ? " dan " : ""}
                <code className="font-mono">{name}</code>
              </span>
            ))}{" "}
            di berkas <code className="font-mono">.env.local</code> untuk
            mengaktifkannya. Tombol yang ditautkan ke halaman yang tidak ada
            lebih merusak kepercayaan daripada tombol yang jujur belum berfungsi.
          </p>
        ) : null}
      </section>

      <p className="text-[13px] text-muted-foreground">
        <Link href="/chat" className="rounded font-medium text-brand-ink underline underline-offset-2">
          Kembali ke chat
        </Link>{" "}
        untuk mencoba alurnya sendiri.
      </p>
    </div>
  );
}
