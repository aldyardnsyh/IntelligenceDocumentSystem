"use client";

import { CircleAlert, Info, RotateCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { AnswerText } from "./answer-text";
import { CitationCard, NoAnswerNotice } from "./citation-card";
import { TypingDots } from "./typing-dots";
import type { UiMessage } from "./use-chat";

/**
 * Penanda jawaban dari pengetahuan umum, bukan dari dokumen.
 *
 * Sengaja ditempatkan di atas jawaban, bukan di bawah: label yang muncul
 * setelah teks panjang sudah terbaca terlambat untuk mencegah salah paham.
 */
function UngroundedNotice() {
  return (
    <div className="mb-3 flex items-start gap-2 rounded-md border border-warning/40 bg-warning/10 px-3 py-2.5">
      <Info className="mt-0.5 size-4 shrink-0 text-warning-ink" aria-hidden />
      <p className="text-[12px] leading-relaxed text-warning-ink">
        <span className="font-medium">Bukan dari dokumen Anda.</span> Tidak ada
        bagian dokumen yang cukup mirip dengan pertanyaan ini, jadi jawaban
        berikut berasal dari pengetahuan umum model dan tidak punya sitasi.
        Verifikasi sebelum dipakai.
      </p>
    </div>
  );
}

interface MessageBubbleProps {
  message: UiMessage;
  onRetry?: () => void;
}

export function MessageBubble({ message, onRetry }: MessageBubbleProps) {
  if (message.role === "user") {
    return (
      <div className="flex justify-end">
        <div className="max-w-[85%] rounded-2xl rounded-br-md bg-primary px-4 py-2.5 text-primary-foreground sm:max-w-[70%]">
          <p className="text-[13px] leading-relaxed whitespace-pre-wrap">{message.content}</p>
        </div>
      </div>
    );
  }

  const streaming = message.state === "streaming";
  const failed = message.state === "error";

  return (
    <div className="flex justify-start">
      <div
        className={`w-full max-w-[92%] rounded-2xl rounded-tl-md bg-card px-4 py-3 ring-1 sm:max-w-full ${
          failed ? "ring-destructive/40" : "ring-border"
        }`}
      >
        {/*
          Indikator mengetik hanya selama token pertama belum tiba. Begitu
          teks flowing, caret di akhir teks yang menandakan masih streaming.
        */}
        {message.state === "thinking" ? (
          <div className="py-1">
            <TypingDots label="Mencari di dokumen" />
          </div>
        ) : null}

        {message.content.length > 0 ? (
          <div className="text-[13px] leading-relaxed whitespace-pre-wrap text-foreground">
            <AnswerText text={message.content} />
          </div>
        ) : null}

        {/*
          Label ini tidak boleh hilang. Jawaban dari pengetahuan umum terlihat
          identik dengan jawaban bersumber dokumen, dan menyamarkan asalnya
          membuat pengguna memakai informasi yang tidak bisa diverifikasi.
        */}
        {message.ungrounded ? <UngroundedNotice /> : null}

        {message.notFound ? <NoAnswerNotice /> : null}
        {message.citations.length > 0 ? <CitationCard citations={message.citations} /> : null}

        {failed ? (
          <div role="alert" className="mt-3 flex flex-col items-start gap-2 rounded-md border border-destructive/30 bg-destructive/5 px-3 py-2.5">
            <p className="flex items-center gap-2 text-[13px] font-medium text-destructive">
              <CircleAlert className="size-4 shrink-0" aria-hidden />
              Jawaban gagal diselesaikan
            </p>
            <p className="text-[12px] leading-relaxed text-foreground/80">
              {message.errorMessage ?? "Terjadi kesalahan saat memproses pertanyaan."}
            </p>
            {onRetry ? (
              <Button variant="outline" size="sm" onClick={onRetry} className="h-7 gap-1.5">
                <RotateCw className="size-3.5" aria-hidden />
                Coba lagi
              </Button>
            ) : null}
          </div>
        ) : null}

        {streaming ? (
          <p className="mt-2 text-[11px] text-muted-foreground">Jawaban masih diterima dari server...</p>
        ) : null}
      </div>
    </div>
  );
}
