"use client";

import { useEffect, useRef, useState } from "react";
import { ArrowUp, Info, Paperclip, Square } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { ACCEPTED_EXTENSIONS, MAX_FILE_BYTES } from "@/lib/mock/store";
import { formatBytes } from "@/lib/format";

interface ChatInputProps {
  onSend: (question: string) => void;
  onStop: () => void;
  isSending: boolean;
  /** null = belum ada dokumen siap, input dikunci dengan alasannya. */
  disabledReason: string | null;
  onAttach: (file: File) => void;
  /** Izinkan jawaban dari pengetahuan umum saat konteks dokumen kosong. */
  allowUngrounded: boolean;
  onAllowUngroundedChange: (value: boolean) => void;
}

export function ChatInput({
  onSend,
  onStop,
  isSending,
  disabledReason,
  onAttach,
  allowUngrounded,
  onAllowUngroundedChange,
}: ChatInputProps) {
  const [value, setValue] = useState("");
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  // Auto-resize sampai empat baris, lalu scroll di dalam textarea.
  useEffect(() => {
    const node = textareaRef.current;
    if (!node) return;
    node.style.height = "auto";
    const lineHeight = 20;
    const max = lineHeight * 4 + 20;
    node.style.height = `${Math.min(node.scrollHeight, max)}px`;
    node.style.overflowY = node.scrollHeight > max ? "auto" : "hidden";
  }, [value]);

  const locked = disabledReason !== null;

  const submit = () => {
    const trimmed = value.trim();
    if (trimmed.length === 0 || isSending || locked) return;
    onSend(trimmed);
    setValue("");
  };

  const input = (
    <div
      className={`flex flex-col gap-2 rounded-xl border bg-card p-2 transition-colors ${
        locked ? "border-border opacity-70" : "border-border focus-within:border-brand"
      }`}
    >
      <Textarea
        ref={textareaRef}
        value={value}
        rows={1}
        disabled={locked}
        onChange={(event) => setValue(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === "Enter" && !event.shiftKey) {
            event.preventDefault();
            submit();
          }
        }}
        placeholder="Tanyakan sesuatu tentang dokumen Anda"
        aria-label="Tulis pertanyaan"
        className="max-h-24 min-h-10 resize-none border-0 bg-transparent px-2 py-1.5 shadow-none focus-visible:ring-0"
      />

      <div className="flex items-center gap-2">
        <input
          ref={fileRef}
          type="file"
          accept={ACCEPTED_EXTENSIONS.join(",")}
          className="sr-only"
          aria-label="Lampirkan dokumen"
          onChange={(event) => {
            const file = event.target.files?.[0];
            if (file) {
              // Atribut `accept` hanya saran di beberapa browser (Safari
              // menyediakan "Semua berkas"), jadi format ikut diperiksa di sini.
              const lower = file.name.toLowerCase();
              if (!ACCEPTED_EXTENSIONS.some((ext) => lower.endsWith(ext))) {
                window.alert("Format tidak didukung. Gunakan berkas PDF, TXT, atau Markdown.");
              } else if (file.size > MAX_FILE_BYTES) {
                window.alert(`Ukuran berkas melebihi ${formatBytes(MAX_FILE_BYTES)}.`);
              } else {
                onAttach(file);
              }
            }
            event.target.value = "";
          }}
        />
        <Button
          type="button"
          variant="ghost"
          size="sm"
          disabled={locked || isSending}
          onClick={() => fileRef.current?.click()}
          className="h-7 gap-1.5 text-muted-foreground"
        >
          <Paperclip className="size-3.5" aria-hidden />
          Lampirkan
        </Button>

        <span className="hidden text-[11px] text-muted-foreground sm:inline">
          Enter untuk kirim, Shift+Enter untuk baris baru
        </span>

        {/*
          Sakelar ini menentukan perilaku sistem saat tidak ada konteks:
          menolak (aman, tapi sering tidak berguna) atau menjawab dari
          pengetahuan umum dengan label. Default menyala supaya pengguna
          tetap mendapat jawaban; mematikannya mengembalikan mode ketat.
        */}
        <label className="ml-auto flex cursor-pointer items-center gap-1.5 text-[11px] text-muted-foreground sm:ml-0">
          <input
            type="checkbox"
            checked={allowUngrounded}
            onChange={(event) => onAllowUngroundedChange(event.target.checked)}
            className="size-3.5 accent-[var(--brand)]"
            disabled={isSending}
          />
          Jawab tanpa dokumen
        </label>

        {isSending ? (
          <Button
            type="button"
            size="icon-sm"
            onClick={onStop}
            className="ml-auto"
            aria-label="Hentikan generasi jawaban"
          >
            <Square className="size-3.5" aria-hidden />
          </Button>
        ) : (
          <Button
            type="button"
            size="icon-sm"
            onClick={submit}
            disabled={locked || value.trim().length === 0}
            className="ml-auto"
            aria-label="Kirim pertanyaan"
          >
            <ArrowUp className="size-4" aria-hidden />
          </Button>
        )}
      </div>
    </div>
  );

  if (!locked) return input;

  // Alasan disable ditulis dua kali: tooltip untuk yang sudah mengarahkan
  // kursor, dan baris teks untuk yang-butuh keyboard atau pembaca layar.
  // Input yang disabled tidak bisa difokus, jadi tooltip saja tidak cukup.
  return (
    <div className="flex flex-col gap-1.5">
      <Tooltip>
        <TooltipTrigger render={<div className="block" />}>{input}</TooltipTrigger>
        <TooltipContent>{disabledReason}</TooltipContent>
      </Tooltip>
      <p className="flex items-center gap-1.5 text-[12px] text-muted-foreground">
        <Info className="size-3.5 shrink-0" aria-hidden />
        {disabledReason}
      </p>
    </div>
  );
}
