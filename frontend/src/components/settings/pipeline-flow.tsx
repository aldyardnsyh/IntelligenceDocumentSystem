"use client";

import Link from "next/link";
import type { ComponentType } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Bot,
  Database,
  FileUp,
  ScanText,
  Scissors,
  Sparkles,
  type LucideIcon,
} from "lucide-react";
import { getHealth } from "@/lib/api";
import { formatNumber } from "@/lib/format";
import { useDocuments } from "@/lib/queries";
import {
  AnswerScene,
  ChunkScene,
  IndexScene,
  OcrScene,
  RetrievalScene,
  UploadScene,
} from "@/components/settings/pipeline-scenes";

interface StageStat {
  value: string;
  label: string;
}

/**
 * Status satu komponen backend: labelnya bergantung pada keadaan yang
 * dilaporkan /health. `key` menunjuk field di hasil useComponentHealth.
 */
interface StageStatus {
  key: "vectorStore" | "llm";
  okLabel: string;
  badLabel: string;
}

interface Stage {
  Icon: LucideIcon;
  title: string;
  body: string;
  chips: readonly string[];
  Scene: ComponentType;
  stats?: readonly StageStat[];
  status?: StageStatus;
  link?: { href: string; label: string };
}

/**
 * Angka hidup di kartu Tahap 1 dan Tahap 3 diambil dari daftar dokumen yang
 * sama dengan halaman /documents. Halaman dan chunk hanya dihitung dari
 * dokumen berstatus siap: dokumen yang sedang diproses belum punya angka yang
 * jujur, dan menampilkannya sebagai 0 justru menyesatkan.
 */
function useLiveCounts() {
  const documents = useDocuments();
  const items = documents.data ?? [];
  const ready = items.filter((item) => item.status === "ready");

  const pages = ready.reduce((total, item) => total + (item.page_count ?? 0), 0);
  const chunks = ready.reduce((total, item) => total + (item.chunk_count ?? 0), 0);

  return {
    hasDocuments: items.length > 0,
    documents: formatNumber(items.length),
    pages: formatNumber(pages),
    chunks: formatNumber(chunks),
  };
}

type ComponentHealth = { vectorStore: boolean; llm: boolean };

/**
 * Status komponen backend di kartu Tahap 4 dan Tahap 5. Kueri ini berbagi
 * cache dengan banner di site-header (kunci ["health"] yang sama), jadi tidak
 * ada permintaan ganda per 60 detik.
 */
function useComponentHealth(): ComponentHealth | null {
  const health = useQuery({
    queryKey: ["health"],
    queryFn: ({ signal }) => getHealth(signal),
    refetchInterval: 60_000,
    retry: false,
  });

  return health.data
    ? {
        vectorStore: health.data.vector_store === "ok",
        llm: health.data.llm === "ok",
      }
    : null;
}

function useStages(live: ReturnType<typeof useLiveCounts>): Stage[] {
  return [
    {
      Icon: FileUp,
      title: "Dokumen diunggah",
      body: "Berkas PDF, TXT, atau Markdown diterima server. Berkas aslinya disimpan untuk pratinjau dan metadata halamannya dicatat — sebelum satu karakter pun diproses.",
      chips: ["PDF · TXT · Markdown", "maks 10 MB"],
      Scene: UploadScene,
      stats: live.hasDocuments
        ? [
            { value: live.documents, label: "dokumen" },
            { value: live.pages, label: "halaman" },
          ]
        : undefined,
    },
    {
      Icon: ScanText,
      title: "Ekstraksi teks (OCR)",
      body: "Halaman hasil scan dibaca OCR yang berjalan lokal — bukan layanan berbayar — lalu teksnya dibersihkan dan urutan bacanya dikembalikan untuk tata letak dua kolom. Halaman dengan keyakinan baca rendah diselamatkan model vision.",
      chips: ["PP-OCR lokal", "rescue VLM bila confidence < 0,55", "tanpa API berbayar"],
      Scene: OcrScene,
    },
    {
      Icon: Scissors,
      title: "Chunking struktur hukum",
      body: "Teks tidak dipotong asal memenuhi kuota karakter. Sistem mengikuti struktur dokumen: satu Pasal menjadi satu chunk, sehingga sitasi menunjuk unit makna yang utuh. Dokumen tanpa struktur hukum memakai jalur paragraf.",
      chips: ["per-Pasal (BAB/Bagian)", "fallback paragraf 500/50"],
      Scene: ChunkScene,
      stats: live.hasDocuments ? [{ value: live.chunks, label: "chunk" }] : undefined,
    },
    {
      Icon: Database,
      title: "Basis pengetahuan",
      body: "Setiap chunk diubah menjadi vektor 768 dimensi oleh model embedding lokal, disimpan di Chroma, dan sekaligus diindeks kata dengan BM25 ber-stemming Sastrawi. Pencarian nanti berjalan dua jalur: semantik dan kata kunci.",
      chips: ["multilingual-e5-base · 768 dim", "Chroma", "BM25 + Sastrawi"],
      Scene: IndexScene,
      status: {
        key: "vectorStore",
        okLabel: "Vector store aktif",
        badLabel: "Vector store terputus",
      },
    },
    {
      Icon: Bot,
      title: "Retrieval & model bahasa",
      body: "Pertanyaan dicocokkan dua jalur, kandidat terbaik dinilai ulang oleh cross-encoder, baru diserahkan ke model bahasa. Hanya bukti yang lolos ambang yang boleh jadi jawaban, dan setiap Pasal dibawa konteks Pasal di sekitarnya.",
      chips: ["bge-reranker-v2-m3", "top-k 5 · ambang 0,78", "Groq"],
      Scene: RetrievalScene,
      status: {
        key: "llm",
        okLabel: "Model bahasa aktif",
        badLabel: "Model bahasa tak terjangkau",
      },
    },
    {
      Icon: Sparkles,
      title: "Jawaban & insight",
      body: "Jawaban datang terstruktur dengan sitasi yang bisa ditelusuri balik ke chunk asalnya — termasuk label jujur saat buktinya lemah atau memang tidak ditemukan. Kualitasnya diukur terus-menerus, bukan diasumsikan.",
      chips: ["sitasi [SUMBER n]", "cache jawaban 30 menit", "trace Langfuse"],
      Scene: AnswerScene,
      link: { href: "/analytics", label: "Lihat evaluasi & log" },
    },
  ];
}

/** Baris status komponen; tanpa data /health, barisnya tidak dirender. */
function StatusRow({ status, health }: { status: StageStatus; health: ComponentHealth }) {
  const ok = health[status.key];

  return (
    <div className="flex items-center gap-1.5 border-t border-border pt-3 text-[12px] text-muted-foreground">
      <span
        className={`size-1.5 rounded-full ${ok ? "bg-success" : "bg-destructive"}`}
        aria-hidden
      />
      {ok ? status.okLabel : status.badLabel}
    </div>
  );
}

export function PipelineFlow() {
  const live = useLiveCounts();
  const health = useComponentHealth();
  const stages = useStages(live);

  return (
    <section className="flex flex-col gap-8" aria-label="Alur sistem dari dokumen menjadi jawaban">
      <ol className="relative flex flex-col gap-10 md:gap-8">
        {/* Rel penghubung: satu garis kontinu dari berkas pertama sampai
            jawaban terakhir. Ikon tiap tahap menutupinya di simpulnya. */}
        <span
          aria-hidden
          className="absolute bottom-12 left-[21px] top-12 w-px bg-border"
        />
        {stages.map((stage, index) => {
          const { Scene, stats, status, link, ...content } = stage;
          return (
            <li
              key={stage.title}
              className="relative grid grid-cols-1 items-center gap-5 md:grid-cols-[minmax(0,1fr)_240px]"
            >
              <span
                className="absolute left-0 top-0 z-10 flex size-11 items-center justify-center rounded-lg bg-card text-brand-ink ring-1 ring-border"
                aria-hidden
              >
                <stage.Icon className="size-5" />
              </span>

              <div className="flex flex-col gap-2.5 pl-14">
                <div className="flex items-baseline gap-2.5">
                  <span className="font-mono text-[11px] text-muted-foreground">
                    {String(index + 1).padStart(2, "0")}
                  </span>
                  <h3 className="text-[15px] font-semibold">{content.title}</h3>
                </div>
                <p className="text-[13px] leading-relaxed text-muted-foreground">
                  {content.body}
                </p>

                {stage.chips.length > 0 ? (
                  <ul className="flex flex-wrap gap-1.5">
                    {stage.chips.map((chip) => (
                      <li
                        key={chip}
                        className="rounded-md bg-muted px-2 py-0.5 font-mono text-[11px] leading-5 text-muted-foreground"
                      >
                        {chip}
                      </li>
                    ))}
                  </ul>
                ) : null}

                {stats ? (
                  <div className="flex gap-8 border-t border-border pt-3">
                    {stats.map((stat) => (
                      <div key={stat.label} className="flex flex-col gap-0.5">
                        <span className="font-mono text-[17px] font-semibold tnum">
                          {stat.value}
                        </span>
                        <span className="text-[11px] text-muted-foreground">{stat.label}</span>
                      </div>
                    ))}
                  </div>
                ) : null}

                {status && health ? (
                  // Tanpa data /health baris ini tidak dirender.
                  <StatusRow status={status} health={health} />
                ) : null}

                {link ? (
                  <p className="border-t border-border pt-3 text-[12px]">
                    <Link
                      href={link.href}
                      className="rounded font-medium text-brand-ink underline underline-offset-2"
                    >
                      {link.label}
                    </Link>
                  </p>
                ) : null}
              </div>

              <div className="pl-14 md:pl-0">
                <div className="overflow-hidden rounded-lg bg-card p-2 ring-1 ring-border">
                  <Scene />
                </div>
              </div>
            </li>
          );
        })}
      </ol>
    </section>
  );
}
