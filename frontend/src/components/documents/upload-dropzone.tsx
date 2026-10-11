"use client";

import { useCallback, useEffect, useId, useRef, useState } from "react";
import { CloudUpload, Loader2 } from "lucide-react";
import { cn } from "cn";
import { Button } from "@/components/ui/button";
import { ACCEPTED_EXTENSIONS, MAX_FILE_BYTES } from "@/lib/mock/store";
import { formatBytes } from "@/lib/format";

interface UploadDropzoneProps {
  onSelect: (file: File) => void;
  busy?: boolean;
  compact?: boolean;
  className?: string;
}

/**
 * Drop zone hanya ada di halaman dokumen. Di /chat, unggah dipanggil dari
 * tombol "Unggah dokumen" supaya area input tetap fokus pada pertanyaan.
 */
export function UploadDropzone({ onSelect, busy = false, compact = false, className }: UploadDropzoneProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  const [localError, setLocalError] = useState<string | null>(null);
  const describedBy = useId();

  const acceptAttr = ACCEPTED_EXTENSIONS.join(",");

  // Menyeret file di luar drop zone membuat browser membuka berkas itu dan
  // mengganti seluruh halaman. State aplikasi (sesi, filter, hasil pencarian)
  // ikut hilang. Pencegahan dilakukan di level window supaya berlaku di mana
  // pun pointer-nya dilepas, bukan hanya di dalam drop zone.
  useEffect(() => {
    const prevent = (event: DragEvent) => {
      event.preventDefault();
    };
    const preventNavigation = (event: DragEvent) => {
      event.preventDefault();
      if (event.dataTransfer) event.dataTransfer.dropEffect = "none";
    };
    window.addEventListener("dragover", prevent);
    window.addEventListener("drop", preventNavigation);
    return () => {
      window.removeEventListener("dragover", prevent);
      window.removeEventListener("drop", preventNavigation);
    };
  }, []);

  const handleFiles = useCallback(
    (files: FileList | null) => {
      const file = files?.[0];
      if (!file) return;

      const lower = file.name.toLowerCase();
      if (!ACCEPTED_EXTENSIONS.some((ext) => lower.endsWith(ext))) {
        setLocalError("Format tidak didukung. Gunakan berkas PDF, TXT, atau Markdown.");
        return;
      }
      if (file.size > MAX_FILE_BYTES) {
        setLocalError(
          `Ukuran berkas ${formatBytes(file.size)} melebihi batas ${formatBytes(MAX_FILE_BYTES)}.`,
        );
        return;
      }

      setLocalError(null);
      onSelect(file);
    },
    [onSelect],
  );

  if (compact) {
    return (
      <>
        <input
          ref={inputRef}
          type="file"
          accept={acceptAttr}
          className="sr-only"
          onChange={(event) => {
            handleFiles(event.target.files);
            event.target.value = "";
          }}
        />
        <Button
          type="button"
          variant="outline"
          disabled={busy}
          onClick={() => inputRef.current?.click()}
          className="gap-1.5"
        >
          {busy ? <Loader2 className="size-4 animate-spin" aria-hidden /> : <CloudUpload className="size-4" aria-hidden />}
          Unggah dokumen
        </Button>
      </>
    );
  }

  return (
    <div className={className}>
      <div
        onDragOver={(event) => {
          event.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(event) => {
          event.preventDefault();
          setDragging(false);
          handleFiles(event.dataTransfer.files);
        }}
        className={cn(
          "flex flex-col items-center gap-3 rounded-lg border-2 border-dashed px-6 py-10 text-center transition-colors",
          dragging ? "border-brand bg-brand-wash" : "border-border bg-card",
        )}
      >
        <span className="flex size-11 items-center justify-center rounded-lg bg-brand-wash text-brand">
          <CloudUpload className="size-5" aria-hidden />
        </span>

        <div className="flex flex-col gap-1">
          <p className="text-[15px] font-semibold">
            Tarik dan lepas berkas ke sini, atau{" "}
            <button
              type="button"
              onClick={() => inputRef.current?.click()}
              disabled={busy}
              className="rounded font-medium text-brand-ink underline underline-offset-2 disabled:pointer-events-none"
            >
              pilih berkas
            </button>
          </p>
          <p className="max-w-md text-[13px] leading-relaxed text-muted-foreground">
            PDF, TXT, atau Markdown sampai {formatBytes(MAX_FILE_BYTES)} per berkas. Ekstraksi teks
            dan pembuatan indeks berjalan otomatis setelah berkas diterima.
          </p>
        </div>

        <input
          ref={inputRef}
          type="file"
          accept={acceptAttr}
          className="sr-only"
          aria-describedby={describedBy}
          disabled={busy}
          onChange={(event) => {
            handleFiles(event.target.files);
            event.target.value = "";
          }}
        />
        <span id={describedBy} className="sr-only">
          Maksimum {formatBytes(MAX_FILE_BYTES)} per berkas.
        </span>

        {localError ? (
          <p role="alert" className="text-[13px] text-destructive">
            {localError}
          </p>
        ) : null}
      </div>
    </div>
  );
}
