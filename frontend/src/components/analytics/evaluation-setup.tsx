"use client";

import { useState } from "react";
import Link from "next/link";
import { FlaskConical, Loader2, Play } from "lucide-react";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/common/empty-state";
import { formatNumber } from "@/lib/format";
import type { DocumentSummary } from "@/types/api";

/**
 * Persiapan evaluasi: pilih dokumen, lalu jalankan.
 *
 * Sebelumnya halaman ini hanya menyuruh "jalankan evaluasi" tanpa menjelaskan
 * apa yang dibutuhkan, dan tanpa cara memilih dokumen. Yang tersedia hanya
 * dataset bawaan, sehingga evaluasi tidak berguna untuk korpus sendiri.
 *
 * Di sini pengguna memilih dokumen yang benar-benar ada di korpus. Pertanyaan
 * dataset yang merujuk dokumen lain otomatis dilewati oleh server, dan kalau
 * tidak ada yang cocok, pesannya menjelaskan kenapa.
 */
export function EvaluationSetup({
  documents,
  isLoading,
  pending,
  onRun,
}: {
  documents: DocumentSummary[];
  isLoading: boolean;
  pending: boolean;
  onRun: (documentIds: string[]) => void;
}) {
  const [selected, setSelected] = useState<string[]>([]);

  const toggle = (id: string) => {
    setSelected((current) =>
      current.includes(id) ? current.filter((item) => item !== id) : [...current, id],
    );
  };

  return (
    <div className="flex flex-col gap-5 rounded-lg border border-border bg-card p-6">
      <div className="flex items-start gap-3">
        <span className="flex size-10 shrink-0 items-center justify-center rounded-lg bg-brand-wash text-brand-ink">
          <FlaskConical className="size-5" aria-hidden />
        </span>
        <div className="flex flex-col gap-1">
          <h2 className="text-[15px] font-semibold">Belum ada data evaluasi</h2>
          <p className="max-w-2xl text-[13px] leading-relaxed text-muted-foreground">
            Evaluasi menjalankan daftar pertanyaan contoh terhadap dokumen yang
            Anda pilih, lalu mengukur berapa yang menemukan sumbernya dan berapa
            pertanyaan &ldquo;tidak ada jawaban&rdquo; yang benar ditolak. Tidak
            butuh API key tambahan.
          </p>
        </div>
      </div>

      {isLoading ? (
        <p className="text-[13px] text-muted-foreground">Memeriksa daftar dokumen...</p>
      ) : documents.length === 0 ? (
        <EmptyState
          Icon={FlaskConical}
          title="Belum ada dokumen siap diuji"
          description="Evaluasi butuh minimal satu dokumen yang sudah selesai diindeks. Unggah dokumen dulu, lalu kembali ke halaman ini."
          action={
            <Button
              variant="outline"
              className="mt-1 gap-1.5"
              render={<Link href="/documents" />}
            >
              Buka halaman Dokumen
            </Button>
          }
        />
      ) : (
        <div className="flex flex-col gap-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <p className="text-[12px] font-medium">
              Pilih dokumen yang mau diuji
            </p>
            <div className="flex items-center gap-3 text-[12px]">
              <button
                type="button"
                onClick={() => setSelected(documents.map((item) => item.id))}
                className="font-medium text-brand-ink underline underline-offset-2 hover:no-underline"
              >
                Pilih semua
              </button>
              {selected.length > 0 ? (
                <button
                  type="button"
                  onClick={() => setSelected([])}
                  className="text-muted-foreground underline underline-offset-2 hover:no-underline"
                >
                  Kosongkan
                </button>
              ) : null}
            </div>
          </div>

          {/*
            Daftar dokumen dengan kotak centang. Dibatasi tingginya supaya
            halaman tetap terbaca saat dokumennya banyak; daftar yang panjang
            mendorong tombolnya keluar dari layar.
          */}
          <ul className="flex max-h-64 flex-col gap-1.5 overflow-y-auto rounded-lg border border-border bg-muted/30 p-2 scrollbar-slim">
            {documents.map((document) => {
              const checked = selected.includes(document.id);
              return (
                <li key={document.id}>
                  <label
                    className={`flex cursor-pointer items-center gap-3 rounded-md px-3 py-2 transition-colors ${
                      checked ? "bg-brand-wash" : "hover:bg-muted"
                    }`}
                  >
                    <input
                      type="checkbox"
                      checked={checked}
                      onChange={() => toggle(document.id)}
                      className="size-4 shrink-0 accent-[var(--brand)]"
                    />
                    <span className="flex min-w-0 flex-1 flex-col">
                      <span className="truncate text-[13px] font-medium">
                        {document.filename}
                      </span>
                      <span className="text-[11px] text-muted-foreground tnum">
                        {formatNumber(document.chunk_count ?? 0)} chunk
                      </span>
                    </span>
                  </label>
                </li>
              );
            })}
          </ul>

          <div className="flex flex-wrap items-center gap-3">
            <Button
              onClick={() => onRun(selected)}
              disabled={pending || selected.length === 0}
              className="gap-1.5"
            >
              {pending ? (
                <>
                  <Loader2 className="size-4 animate-spin" aria-hidden />
                  Menjalankan...
                </>
              ) : (
                <>
                  <Play className="size-4" aria-hidden />
                  Jalankan evaluasi
                </>
              )}
            </Button>
            <p className="text-[12px] text-muted-foreground">
              {selected.length === 0
                ? "Pilih minimal satu dokumen."
                : `${selected.length} dokumen dipilih.`}
            </p>
          </div>

          <p className="text-[12px] leading-relaxed text-muted-foreground">
            Pertanyaan yang merujuk dokumen lain otomatis dilewati, karena
            menjalankannya pada korpus ini akan selalu bernilai nol dan bukan
            ukuran kualitas retrieval Anda. Untuk memakai seluruh dataset
            bawaan, jalankan{" "}
            <code className="font-mono text-[11px]">python -m scripts.seed_demo</code>{" "}
            di folder <code className="font-mono text-[11px]">backend</code> lalu
            pilih dokumen{" "}
            <code className="font-mono text-[11px]">contoh-sop-layanan.md</code>.
          </p>
        </div>
      )}
    </div>
  );
}