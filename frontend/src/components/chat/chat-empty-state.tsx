"use client";

import { MessageSquare, Upload } from "lucide-react";
import { Button } from "@/components/ui/button";
import type { DocumentSummary } from "@/types/api";

interface ChatEmptyStateProps {
  documents: DocumentSummary[];
  onPick: (question: string) => void;
  onUpload: () => void;
}

/**
 * Pertanyaan awal dibuat dari nama dokumen yang benar-benar ada, bukan teks
 * contoh hardcoded. Kalau nama dokumen tidak menghasilkan pertanyaan yang
 * masuk akal, bagian ini disembunyikan seluruhnya, bukan diisi kalimat generik.
 */
function suggestFrom(documents: DocumentSummary[]): string[] {
  const suggestions: string[] = [];

  for (const document of documents.slice(0, 3)) {
    const stem = document.filename
      .replace(/\.[^.]+$/, "")
      .replace(/[_-]+/g, " ")
      .trim();

    if (stem.length < 3) continue;

    suggestions.push(`Ringkas poin utama dari ${stem}`);
    if (suggestions.length >= 3) break;
  }

  return suggestions;
}

export function ChatEmptyState({ documents, onPick, onUpload }: ChatEmptyStateProps) {
  const suggestions = suggestFrom(documents);
  const hasReadyDocument = documents.length > 0;

  return (
    <div className="mx-auto flex w-full max-w-[640px] flex-col items-center gap-5 py-12 text-center">
      <span className="flex size-10 items-center justify-center rounded-lg bg-muted text-muted-foreground">
        <MessageSquare className="size-5" aria-hidden />
      </span>

      <div className="flex flex-col gap-1.5">
        <h2 className="text-[15px] font-semibold">
          {hasReadyDocument
            ? "Mulai percakapan dengan dokumen Anda"
            : "Unggah dokumen untuk mulai bertanya"}
        </h2>
        <p className="max-w-md text-[13px] leading-relaxed text-muted-foreground">
          {hasReadyDocument
            ? "Ajukan pertanyaan spesifik. Jawaban akan disusun dari chunk dokumen dan disertai sumbernya."
            : "Sistem menjawab hanya dari dokumen yang sudah diunggah. Tanpa dokumen, tidak ada sumber untuk dijawab."}
        </p>
      </div>

      {hasReadyDocument && suggestions.length > 0 ? (
        <ul className="flex w-full flex-col gap-2">
          {suggestions.map((suggestion) => (
            <li key={suggestion}>
              <Button
                variant="outline"
                className="h-auto w-full justify-start py-2.5 text-left text-[13px]"
                onClick={() => onPick(suggestion)}
              >
                {suggestion}
              </Button>
            </li>
          ))}
        </ul>
      ) : null}

      {!hasReadyDocument ? (
        <Button className="gap-2" onClick={onUpload}>
          <Upload className="size-4" aria-hidden />
          Unggah dokumen
        </Button>
      ) : null}
    </div>
  );
}
