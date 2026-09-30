"use client";

import { useState } from "react";
import Link from "next/link";
import { ChevronRight, FileText, SearchX } from "lucide-react";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { formatPercent, truncateMiddle } from "@/lib/format";
import type { Citation } from "@/types/api";

interface CitationCardProps {
  citations: Citation[];
}

/**
 * Sitasi adalah bagian paling penting di produk ini: pengguna tidak akan
 * percaya jawaban AI tanpa bisa membuka sumbernya. Karena itu setiap kartu
 * sumber adalah tautan nyata ke chunk asal di /documents/[id], bukan
 * pratinjau yang berdiri sendiri.
 */
export function CitationCard({ citations }: CitationCardProps) {
  const [open, setOpen] = useState(false);

  if (citations.length === 0) return null;

  return (
    <Collapsible open={open} onOpenChange={setOpen} className="mt-3">
      <CollapsibleTrigger
        render={
          <button
            type="button"
            className="flex w-full items-center gap-2 rounded-md border border-border bg-card px-3 py-2 text-left text-[13px] font-medium transition-colors hover:bg-muted"
          />
        }
      >
        <FileText className="size-3.5 shrink-0 text-brand" aria-hidden />
        <span>
          {citations.length} sumber ditemukan
        </span>
        <span className="ml-auto flex items-center gap-1 text-[12px] font-normal text-muted-foreground">
          Lihat sumber
          <ChevronRight
            className={`size-3.5 transition-transform ${open ? "rotate-90" : ""}`}
            aria-hidden
          />
        </span>
      </CollapsibleTrigger>

      <CollapsibleContent>
        <ul className="mt-2 flex flex-col gap-2">
          {citations.map((citation) => (
            <li key={`${citation.document_id}-${citation.chunk_index}`}>
              <Link
                href={`/documents/${citation.document_id}?chunk=${citation.chunk_index}`}
                className="flex flex-col gap-1 rounded-md border border-border bg-card px-3 py-2.5 transition-colors hover:border-brand hover:bg-brand-wash"
              >
                <span className="flex flex-wrap items-center gap-x-2 gap-y-1 text-[12px]">
                  <span className="font-medium text-foreground">
                    {truncateMiddle(citation.document_name, 40)}
                  </span>
                  <span className="text-muted-foreground">
                    {citation.page_number !== null
                      ? `Hal. ${citation.page_number}`
                      : `Chunk #${citation.chunk_index + 1}`}
                  </span>
                  <span className="ml-auto font-mono text-muted-foreground tnum">
                    skor {formatPercent(citation.score)}
                  </span>
                </span>
                <span className="line-clamp-3 text-[12px] leading-relaxed text-muted-foreground">
                  {citation.excerpt}
                </span>
              </Link>
            </li>
          ))}
        </ul>
      </CollapsibleContent>
    </Collapsible>
  );
}

/** Varian untuk jawaban "tidak ditemukan": menjelaskan, tidak menyalahkan. */
export function NoAnswerNotice() {
  return (
    <div className="mt-3 flex items-start gap-2 rounded-md border border-warning/40 bg-warning/5 px-3 py-2.5">
      <SearchX className="mt-0.5 size-4 shrink-0 text-warning-ink" aria-hidden />
      <p className="text-[12px] leading-relaxed text-foreground/85">
        Sistem tidak menemukan chunk yang cukup mirip dengan pertanyaan Anda, jadi
        jawaban tidak bisa disusun dari dokumen. Ini ditampilkan daripada
        menebak, karena jawaban tanpa sumber berisiko menyesatkan.
      </p>
    </div>
  );
}
