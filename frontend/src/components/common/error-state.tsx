"use client";

import { AlertCircle, RotateCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { ApiError } from "@/lib/api/error";

interface ErrorStateProps {
  error: unknown;
  onRetry?: () => void;
  title?: string;
  className?: string;
}

/**
 * Error dimunculkan per komponen, bukan menjatuhkan seluruh halaman ke /error.
 * Satu endpoint yang gagal tidak boleh membuat dashboard tidak bisa dipakai
 * (design.md 12).
 */
export function ErrorState({ error, onRetry, title = "Gagal memuat data", className }: ErrorStateProps) {
  const message = error instanceof ApiError
    ? error.message
    : error instanceof Error
      ? error.message
      : "Terjadi kesalahan yang tidak terduga.";

  const canRetry = typeof onRetry === "function" && !(error instanceof ApiError && error.isAuthFailure);

  return (
    <div
      role="alert"
      className={`flex flex-col items-start gap-2 rounded-lg border border-destructive/30 bg-destructive/5 px-4 py-3 ${className ?? ""}`}
    >
      <p className="flex items-center gap-2 text-[13px] font-medium text-destructive">
        <AlertCircle className="size-4 shrink-0" aria-hidden />
        {title}
      </p>
      <p className="text-[13px] leading-relaxed text-foreground/80">{message}</p>
      {canRetry ? (
        <Button variant="outline" size="sm" onClick={onRetry} className="mt-1 gap-1.5">
          <RotateCw className="size-3.5" aria-hidden />
          Coba lagi
        </Button>
      ) : null}
    </div>
  );
}
