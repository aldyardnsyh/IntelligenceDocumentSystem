"use client";

import { useMemo, useState } from "react";
import { FileText, Search } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
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
 * Sebelumnya scope hanya bisa satu dokumen, lewat tautan `?doc=` dari halaman
 * detail. Itu cukup untuk alur "tanya dokumen ini", tapi tidak untuk
 * pertanyaan yang jawabannya tersebar di beberapa dokumen, misalnya "apa saja
 * kewajiban vendor di kontrak dan SOP pengadaan".
 *
 * Daftar kosong sengaja berarti "semua dokumen", bukan "tidak ada dokumen".
 * Kalau kosong berarti tidak ada, pengguna yang belum memilih apa pun akan
 * mendapat penolakan untuk setiap pertanyaan, dan itu terbaca seperti
 * aplikasi rusak.
 */
export function DocumentScopePicker({
  documents,
  selected,
  onChange,
  disabled = false,
  lockedId = null,
}: DocumentScopePickerProps) {
  const [cari, setCari] = useState("");

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
    <DropdownMenu>
      <DropdownMenuTrigger
        render={
          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={disabled}
            className="h-8 max-w-[240px] gap-1.5 text-[12px]"
            title="Batasi pencarian ke dokumen tertentu"
          />
        }
      >
        <FileText className="size-3.5 shrink-0" aria-hidden />
        <span className="truncate">{label}</span>
      </DropdownMenuTrigger>

      <DropdownMenuContent align="start" className="w-[300px] p-0">
        <div className="border-b border-border p-2">
          <div className="relative">
            <Search
              className="pointer-events-none absolute top-1/2 left-2 size-3.5 -translate-y-1/2 text-muted-foreground"
              aria-hidden
            />
            <Input
              value={cari}
              onChange={(event) => setCari(event.target.value)}
              onKeyDown={(event) => {
                // Jangan biarkan panah atas atau bawah memindahkan fokus
                // keluar dari kolom pencarian saat pengguna sedang mengetik.
                event.stopPropagation();
              }}
              placeholder="Cari dokumen"
              aria-label="Cari dokumen"
              className="h-8 pl-7 text-[12px]"
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
            tersaring.map((item) => (
              <DropdownMenuCheckboxItem
                key={item.id}
                checked={selected.includes(item.id)}
                onCheckedChange={() => toggle(item.id)}
                // Menu tidak ditutup setiap kali memilih, karena pengguna
                // biasanya memilih lebih dari satu dokumen sekaligus.
                onSelect={(event) => event.preventDefault()}
                disabled={
                  (!selected.includes(item.id) && batasTercapai) ||
                  item.id === lockedId
                }
                className="text-[12px]"
              >
                <span className="truncate">{item.filename}</span>
                {item.id === lockedId ? (
                  <span className="ml-auto shrink-0 text-[10px] text-muted-foreground">
                    terkunci
                  </span>
                ) : null}
              </DropdownMenuCheckboxItem>
            ))
          )}
        </div>

        <DropdownMenuSeparator />
        <DropdownMenuLabel className="flex items-center justify-between gap-2 text-[11px] font-normal text-muted-foreground">
          <span>
            {selected.length === 0
              ? "Tanpa pilihan berarti semua dokumen."
              : `${selected.length} dari ${MAX_SCOPE_DOCUMENTS} dokumen.`}
          </span>
          {selected.some((id) => id !== lockedId) ? (
            <button
              type="button"
              className="rounded px-1 font-medium text-brand-ink underline underline-offset-2 hover:no-underline"
              onClick={() =>
                onChange(hapusPilihanTerpilih(lockedId, selected))
              }
            >
              Hapus
            </button>
          ) : null}
        </DropdownMenuLabel>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
