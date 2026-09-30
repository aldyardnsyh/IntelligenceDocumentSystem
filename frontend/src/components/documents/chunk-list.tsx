"use client";

import { useEffect, useRef } from "react";
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from "@/components/ui/accordion";
import { Badge } from "@/components/ui/badge";
import type { Chunk } from "@/types/api";

interface ChunkListProps {
  documentId: string;
  chunks: Chunk[];
  /** Chunk yang berasal dari klik sitasi di /chat (design.md 6). */
  highlightChunkIndex?: number | null;
}

export function ChunkList({ documentId, chunks, highlightChunkIndex }: ChunkListProps) {
  const scrollerRef = useRef<HTMLDivElement>(null);
  const highlightRef = useRef<HTMLDivElement>(null);

  // Menuju chunk tertentu dari sitasi: buka, lalu scroll ke posisinya.
  useEffect(() => {
    if (highlightChunkIndex === null || highlightChunkIndex === undefined) return;
    const node = highlightRef.current;
    const scroller = scrollerRef.current;
    if (!node || !scroller) return;
    scroller.scrollTo({ top: node.offsetTop - 16, behavior: "smooth" });
  }, [highlightChunkIndex]);

  return (
    <div ref={scrollerRef} className="max-h-[70vh] overflow-y-auto scrollbar-slim pr-1">
      <Accordion
        className="rounded-lg bg-card ring-1 ring-border"
        // Satu chunk terbuka pada satu waktu: membandingkan dua chunk
        // berdampingan adalah kasus yang jarang, dan accordion yang bisa
        // dibuka semua menghasilkan daftar setinggi dokumen penuh.
        defaultValue={
          highlightChunkIndex === null || highlightChunkIndex === undefined
            ? []
            : [String(highlightChunkIndex)]
        }
      >
        {chunks.map((chunk) => {
          const isHighlighted = chunk.chunk_index === highlightChunkIndex;
          return (
            <div
              key={chunk.id}
              ref={isHighlighted ? highlightRef : undefined}
              className={isHighlighted ? "bg-brand-wash" : undefined}
            >
              <AccordionItem value={String(chunk.chunk_index)}>
                <AccordionTrigger className="px-4 py-3 hover:no-underline">
                  <span className="flex min-w-0 flex-wrap items-center gap-2">
                    <span className="font-mono text-[12px] font-medium text-primary tnum">
                      #{String(chunk.chunk_index + 1).padStart(3, "0")}
                    </span>
                    <span className="truncate text-[13px]">
                      {chunk.page_number !== null
                        ? `Halaman ${chunk.page_number}`
                        : "Bagian teks"}
                    </span>
                    {isHighlighted ? (
                      <Badge variant="secondary" className="bg-brand/15 text-brand-ink">
                        Dari sitasi
                      </Badge>
                    ) : null}
                  </span>
                  {chunk.token_count ? (
                    <span className="ml-auto shrink-0 font-mono text-[11px] text-muted-foreground tnum">
                      {chunk.token_count} token
                    </span>
                  ) : null}
                </AccordionTrigger>
                <AccordionContent className="px-4">
                  <div className="rounded-md border border-border bg-muted/40 p-3">
                    <p className="font-mono text-[12px] leading-relaxed whitespace-pre-wrap text-foreground/85">
                      {chunk.content}
                    </p>
                  </div>
                  <p className="mt-2 font-mono text-[11px] text-muted-foreground">
                    id: {documentId}.{chunk.chunk_index}
                  </p>
                </AccordionContent>
              </AccordionItem>
            </div>
          );
        })}
      </Accordion>
    </div>
  );
}
