"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { AlertCircle, ExternalLink, FileQuestionMark, FileText } from "lucide-react";
import { EmptyState } from "@/components/common/empty-state";
import { ErrorState } from "@/components/common/error-state";
import { Button } from "@/components/ui/button";
import { getDocumentFileUrl, getDocumentPreview } from "@/lib/api";
import { queryKeys } from "@/lib/queries";
import { formatNumber } from "@/lib/format";

/**
 * Pratinjau isi dokumen untuk cross-check.
 *
 * Dua bentuk, dipilih menurut jenis berkasnya:
 *
 * - **PDF**: berkas aslinya ditampilkan di iframe. Ini yang dibutuhkan untuk
 *   memeriksa ekstraksi teks: tata letak, tabel, dan halaman yang gagal
 *   terbaca hanya terlihat di berkas aslinya. Teks hasil parsing tetap
 *   tersedia di tab di bawahnya.
 * - **Teks/Markdown**: teks hasil parsing ditampilkan berurutan, karena
 *   berkas aslinya tidak disimpan untuk jenis ini.
 *
 * Yang dirender selalu berasal dari server sendiri (`/api/v1/...`), bukan URL
 * luar, dan PDF ditampilkan lewat iframe dengan `sandbox` supaya isi dokumen
 * tidak bisa menjalankan skrip di halaman aplikasi.
 *
 * Satu pengecualian: di mode demo berkas asli berupa blob yang hanya hidup
 * selama sesi, jadi setelah muat ulang URL-nya kosong. Iframe dengan `src`
 * kosong justru memuat halaman ini sendiri, sehingga kasus itu ditampilkan
 * sebagai empty state dengan jalan keluar ke teks hasil ekstraksi.
 */
export function DocumentPreview({
  documentId,
  filename,
}: {
  documentId: string;
  filename: string;
}) {
  const isPdf = filename.toLowerCase().endsWith(".pdf");
  const [showText, setShowText] = useState(!isPdf);
  const fileUrl = getDocumentFileUrl(documentId);

  const preview = useQuery({
    queryKey: queryKeys.documentPreview(documentId),
    queryFn: ({ signal }) => getDocumentPreview(documentId, signal),
    retry: false,
  });

  if (isPdf && !showText) {
    if (!fileUrl) {
      return (
        <EmptyState
          Icon={FileQuestionMark}
          title="Pratinjau tidak tersedia"
          description="Berkas asli PDF tidak tersimpan di peramban ini, jadi pratinjau tidak bisa dibuka lagi setelah halaman dimuat ulang. Teks hasil ekstraksi tetap bisa dibaca di tab Chunk hasil ingestion."
          action={
            <Button
              type="button"
              variant="outline"
              className="mt-1"
              onClick={() => setShowText(true)}
            >
              Lihat teks hasil ekstraksi
            </Button>
          }
        />
      );
    }

    return (
      <div className="flex flex-col gap-3">
        <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-border bg-muted/40 px-4 py-2.5">
          <p className="flex items-center gap-2 text-[12px] text-muted-foreground">
            <FileText className="size-3.5 shrink-0" aria-hidden />
            Berkas asli yang diunggah, ditampilkan apa adanya.
          </p>
          <div className="flex items-center gap-3">
            <button
              type="button"
              onClick={() => setShowText(true)}
              className="text-[12px] font-medium text-brand-ink underline underline-offset-2 hover:no-underline"
            >
              Lihat teks hasil ekstraksi
            </button>
            <a
              href={fileUrl}
              target="_blank"
              rel="noreferrer noopener"
              className="flex items-center gap-1 text-[12px] font-medium text-brand-ink underline underline-offset-2 hover:no-underline"
            >
              Buka di tab baru
              <ExternalLink className="size-3" aria-hidden />
            </a>
          </div>
        </div>

        {/*
          `sandbox` tanpa `allow-scripts`: PDF tidak butuh skrip, dan
          mengizinkannya berarti isi dokumen pengguna bisa menjalankan kode di
          origin aplikasi. `allow-same-origin` juga tidak diberikan supaya
          iframe tidak bisa menyentuh storage aplikasi.
        */}
        <iframe
          src={fileUrl}
          title={`Pratinjau ${filename}`}
          sandbox=""
          className="h-[70vh] w-full rounded-lg bg-card ring-1 ring-border"
        />

        <p className="text-[12px] leading-relaxed text-muted-foreground">
          Bandingkan tampilan di atas dengan tab <span className="font-medium">Chunk
          hasil ingestion</span>. Kalau ada bagian yang terlihat di PDF tapi
          tidak muncul di chunk, ekstraksi teksnya yang gagal membaca bagian
          itu.
        </p>
      </div>
    );
  }

  if (preview.isPending) {
    return (
      <div className="flex flex-col gap-3 rounded-lg bg-card p-5 ring-1 ring-border" aria-hidden>
        {[0, 1, 2, 3].map((index) => (
          <div key={index} className="h-4 rounded bg-muted" />
        ))}
      </div>
    );
  }

  if (preview.isError) {
    return <ErrorState error={preview.error} onRetry={() => preview.refetch()} />;
  }

  const data = preview.data;

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-border bg-muted/40 px-4 py-2.5">
        <p className="flex items-center gap-2 text-[12px] text-muted-foreground">
          <FileText className="size-3.5 shrink-0" aria-hidden />
          Teks hasil ekstraksi, disusun berurutan seperti di dokumen aslinya.
        </p>
        <div className="flex items-center gap-3">
          {isPdf ? (
            <button
              type="button"
              onClick={() => setShowText(false)}
              className="text-[12px] font-medium text-brand-ink underline underline-offset-2 hover:no-underline"
            >
              Lihat berkas asli
            </button>
          ) : null}
          <p className="text-[11px] text-muted-foreground tnum">
            {formatNumber(data.chunk_count)} chunk · {formatNumber(data.total_chars)} karakter
          </p>
        </div>
      </div>

      {data.truncated ? (
        <p className="flex items-start gap-2 rounded-lg border border-warning/40 bg-warning/10 px-4 py-2.5 text-[12px] leading-relaxed text-warning-ink">
          <AlertCircle className="mt-0.5 size-3.5 shrink-0" aria-hidden />
          Isi yang ditampilkan dipotong karena dokumennya sangat panjang. Yang
          Anda baca di bawah bukan keseluruhan berkas.
        </p>
      ) : null}

      {/*
        Teks ditampilkan dengan `whitespace-pre-wrap` supaya baris dan
        paragrafnya tetap seperti di dokumen. Tidak ada HTML yang dirender,
        jadi isi dokumen tidak pernah dieksekusi sebagai markup.
      */}
      <article className="max-h-[70vh] overflow-y-auto rounded-lg bg-card p-5 text-[13px] leading-relaxed whitespace-pre-wrap ring-1 ring-border scrollbar-slim">
        {data.content}
      </article>
    </div>
  );
}