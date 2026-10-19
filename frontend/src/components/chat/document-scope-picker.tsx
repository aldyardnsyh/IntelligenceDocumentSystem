"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { Check, FileText, Search, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { hapusPilihanTerpilih } from "@/lib/chat/scope";
import type { DocumentSummary } from "@/types/api";

/** Batas yang sama dengan `document_ids` di skema backend. */
export const MAX_SCOPE_DOCUMENTS = 20;

interface DocumentScopePickerProps {
  documents: DocumentSummary[];
  /** Dokumen yang sedang dipilih. Daftar kosong berarti semua dokumen. */
  selected: string[];
  onChange: (ids: string[]) => void;
  /** Tombol dinonaktifkan selama jawaban masih mengalir. */
  disabled?: boolean;
  /**
   * Dokumen dari `?doc=` yang mengunci scope, misalnya saat pengguna menekan
   * "Tanya dokumen ini". Dokumen ini selalu tampil terpilih dan tidak bisa
   * dilepas, karena melepasnya berarti pencarian melebar tanpa pengguna
   * memintanya.
   */
  lockedId?: string | null;
}

/**
 * Pemilih beberapa dokumen sebagai scope percakapan.
 *
 * Panel ini sengaja TIDAK memakai komponen menu. Versi sebelumnya memakai
 * `DropdownMenu` dari Base UI dan menyisipkan kotak pencarian serta teks
 * bantuan di dalam popup-nya. Itu melanggar kontrak komponen menu: isi popup
 * harus berupa item menu, bukan input atau paragraf. Akibatnya Base UI
 * melempar error (kode 31) saat popup dibuka, error boundary menangkapnya, dan
 * seluruh halaman chat berubah menjadi "Terjadi kesalahan pada server".
 *
 * Panel biasa dengan `position: absolute` tidak punya batasan itu, dan
 * perilakunya lebih jelas untuk pemilih yang memang berisi pencarian dan
 * banyak pilihan.
 *
 * Daftar kosong berarti "semua dokumen", bukan "tidak ada dokumen". Kalau
 * artinya tertukar, pengguna yang belum memilih apa pun akan ditolak di setiap
 * pertanyaan, dan itu terbaca seperti aplikasi rusak.
 */
export function DocumentScopePicker({
  documents,
  selected,
  onChange,
  disabled = false,
  lockedId = null,
}: DocumentScopePickerProps) {
  const [terbuka, setTerbuka] = useState(false);
  const [cari, setCari] = useState("");
  const wadah = useRef<HTMLDivElement>(null);

  const siap = useMemo(
    () => documents.filter((item) => item.status === "ready"),
    [documents],
  );

  const tersaring = useMemo(() => {
    const kata = cari.trim().toLowerCase();
    if (!kata) return siap;
    return siap.filter((item) => item.filename.toLowerCase().includes(kata));
  }, [siap, cari]);

  const terpilih = useMemo(
    () => siap.filter((item) => selected.includes(item.id)),
    [siap, selected],
  );

  const batasTercapai = selected.length >= MAX_SCOPE_DOCUMENTS;

  // Tutup panel saat klik di luar atau tekan Escape. Tanpa ini, panel tetap
  // terbuka saat pengguna mengklik area lain dan menghalangi halaman.
  useEffect(() => {
    if (!terbuka) return;

    const klikLuar = (event: MouseEvent) => {
      if (wadah.current && !wadah.current.contains(event.target as Node)) {
        setTerbuka(false);
      }
    };
    const tombolEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setTerbuka(false);
    };

    document.addEventListener("mousedown", klikLuar);
    document.addEventListener("keydown", tombolEscape);
    return () => {
      document.removeEventListener("mousedown", klikLuar);
      document.removeEventListener("keydown", tombolEscape);
    };
  }, [terbuka]);

  const toggle = (id: string) => {
    // Dokumen yang dikunci tidak bisa dilepas lewat klik.
    if (id === lockedId) return;

    if (selected.includes(id)) {
      onChange(selected.filter((item) => item !== id));
      return;
    }
    if (batasTercapai) return;
    onChange([...selected, id]);
  };

  const label =
    terpilih.length === 0
      ? "Semua dokumen"
      : terpilih.length === 1
        ? terpilih[0].filename
        : `${terpilih.length} dokumen dipilih`;

  return (
    <div ref={wadah} className="relative">
      <Button
        type="button"
        variant="outline"
        size="sm"
        disabled={disabled}
        onClick={() => setTerbuka((sebelumnya) => !sebelumnya)}
        aria-expanded={terbuka}
        aria-haspopup="dialog"
        className="h-8 max-w-[240px] gap-1.5 text-[12px]"
        title="Batasi pencarian ke dokumen tertentu"
      >
        <FileText className="size-3.5 shrink-0" aria-hidden />
        <span className="truncate">{label}</span>
      </Button>

      {terbuka ? (
        <div
          role="dialog"
          aria-label="Pilih dokumen sebagai scope percakapan"
          className="absolute top-full left-0 z-50 mt-1 w-[300px] overflow-hidden rounded-lg bg-popover text-popover-foreground shadow-md ring-1 ring-foreground/10"
        >
          <div className="border-b border-border p-2">
            <div className="relative">
              <Search
                className="pointer-events-none absolute top-1/2 left-2 size-3.5 -translate-y-1/2 text-muted-foreground"
                aria-hidden
              />
              <Input
                value={cari}
                onChange={(event) => setCari(event.target.value)}
                placeholder="Cari dokumen"
                aria-label="Cari dokumen"
                className="h-8 pl-7 text-[12px]"
                autoFocus
              />
            </div>
          </div>

          <div className="max-h-[260px] overflow-y-auto scrollbar-slim py-1">
            {siap.length === 0 ? (
              <p className="px-2 py-6 text-center text-[12px] text-muted-foreground">
                Belum ada dokumen yang siap ditanyai.
              </p>
            ) : tersaring.length === 0 ? (
              <p className="px-2 py-6 text-center text-[12px] text-muted-foreground">
                Tidak ada dokumen yang cocok.
              </p>
            ) : (
              tersaring.map((item) => {
                const aktif = selected.includes(item.id);
                const terkunci = item.id === lockedId;
                return (
                  <button
                    key={item.id}
                    type="button"
                    role="checkbox"
                    aria-checked={aktif}
                    aria-label={item.filename}
                    onClick={() => toggle(item.id)}
                    disabled={terkunci || (!aktif && batasTercapai)}
                    className="flex w-full items-center gap-2 px-2 py-1.5 text-left text-[12px] hover:bg-muted disabled:cursor-not-allowed disabled:opacity-60"
                  >
                    <span
                      className={`flex size-3.5 shrink-0 items-center justify-center rounded border ${
                        aktif
                          ? "border-brand bg-brand text-primary-foreground"
                          : "border-border"
                      }`}
                      aria-hidden
                    >
                      {aktif ? <Check className="size-2.5" /> : null}
                    </span>
                    <span className="truncate">{item.filename}</span>
                    {terkunci ? (
                      <span className="ml-auto shrink-0 text-[10px] text-muted-foreground">
                        terkunci
                      </span>
                    ) : null}
                  </button>
                );
              })
            )}
          </div>

          <div className="flex items-center justify-between gap-2 border-t border-border p-2">
            <p className="text-[11px] text-muted-foreground">
              {selected.length === 0
                ? "Tanpa pilihan berarti semua dokumen."
                : `${selected.length} dari ${MAX_SCOPE_DOCUMENTS} dokumen.`}
            </p>
            <div className="flex items-center gap-1">
              {selected.some((id) => id !== lockedId) ? (
                <button
                  type="button"
                  className="rounded px-1 text-[11px] font-medium text-brand-ink underline underline-offset-2 hover:no-underline"
                  onClick={() => onChange(hapusPilihanTerpilih(lockedId, selected))}
                >
                  Hapus
                </button>
              ) : null}
              <Button
                type="button"
                variant="ghost"
                size="icon-xs"
                aria-label="Tutup pemilih dokumen"
                onClick={() => setTerbuka(false)}
              >
                <X className="size-3.5" aria-hidden />
              </Button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}
