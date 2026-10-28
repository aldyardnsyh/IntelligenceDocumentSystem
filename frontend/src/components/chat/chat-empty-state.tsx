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
 * Pertanyaan contoh tetap, bukan diturunkan dari nama berkas. Tujuannya
 * menunjukkan bentuk pertanyaan yang bisa dijawab dokumen (SOP, tiket, cuti)
 * dan mengisi kotak tanya saja, bukan langsung mengirim.
 */
const SUGGESTED_QUESTIONS = [
  "Berapa lama target penyelesaian permintaan menurut SOP layanan?",
  "Apa langkah pertama saat membuat tiket layanan?",
  "Berapa sisa cuti tahunan yang bisa dibawa ke tahun berikutnya?",
];

export function ChatEmptyState({ documents, onPick, onUpload }: ChatEmptyStateProps) {
  const hasReadyDocument = documents.length > 0;

  return (
    <div className="mx-auto flex w-full max-w-[640px] flex-col items-center gap-5 py-12 text-center">
      <span className="flex size-10 items-center justify-center rounded-lg bg-muted text-muted-foreground">
        <MessageSquare className="size-5" aria-hidden />
      </span>

      <div className="flex flex-col gap-1.5">
        <h2 className="text-[15px] font-semibold">
          {hasReadyDocument
            ? "Tanya dokumen Anda"
            : "Unggah dokumen untuk mulai bertanya"}
        </h2>
        <p className="max-w-md text-[13px] leading-relaxed text-muted-foreground">
          {hasReadyDocument
            ? "Pilih salah satu pertanyaan contoh, atau tulis pertanyaan sendiri."
            : "Sistem menjawab hanya dari dokumen yang sudah diunggah. Tanpa dokumen, tidak ada sumber untuk dijawab."}
        </p>
      </div>

      {hasReadyDocument ? (
        <ul className="flex w-full flex-col gap-2">
          {SUGGESTED_QUESTIONS.map((suggestion) => (
            <li key={suggestion}>
              <Button
                type="button"
                variant="outline"
                className="h-auto w-full justify-start whitespace-normal py-2.5 text-left text-[13px]"
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
