"use client";

import { ArrowDownRight, ArrowUpRight, Minus } from "lucide-react";
import { cn } from "cn";

export type StatTone = "success" | "warning" | "error" | "neutral";

const TONE_TEXT: Record<StatTone, string> = {
  success: "text-success-ink",
  warning: "text-warning-ink",
  error: "text-destructive",
  neutral: "text-muted-foreground",
};

const TONE_BAR: Record<StatTone, string> = {
  success: "bg-success",
  warning: "bg-warning",
  error: "bg-destructive",
  neutral: "bg-muted-foreground",
};

interface StatCardProps {
  label: string;
  value: string;
  /** Kalimat pembanding target. Tanpa ini, angka besar tidak berarti apa pun. */
  helper: string;
  tone?: StatTone;
  /** 0..1, mengisi garis dasar kartu. Null = tidak ada data untuk diukur. */
  progress?: number | null;
  trend?: { direction: "up" | "down" | "flat"; label: string };
}

/**
 * Kartu statistik hanya dipakai kalau angkanya berasal dari pengukuran nyata.
 * Kalau belum ada run evaluasi, halaman menampilkan empty state, bukan angka
 * contoh (R-17, R-38).
 */
export function StatCard({
  label,
  value,
  helper,
  tone = "neutral",
  progress = null,
  trend,
}: StatCardProps) {
  const TrendIcon =
    trend?.direction === "up" ? ArrowUpRight : trend?.direction === "down" ? ArrowDownRight : Minus;

  return (
    <div className="relative flex flex-col gap-2 overflow-hidden rounded-lg bg-card p-5 ring-1 ring-border">
      <p className="eyebrow">{label}</p>
      <p className="text-3xl font-semibold tracking-tight text-primary tnum">{value}</p>
      <p className={cn("text-[12px] leading-relaxed", TONE_TEXT[tone])}>{helper}</p>
      {trend ? (
        <p className={cn("flex items-center gap-1 text-[12px]", TONE_TEXT[tone])}>
          <TrendIcon className="size-3.5" aria-hidden />
          {trend.label}
        </p>
      ) : null}

      {/*
        Garis di dasar kartu memvisualkan posisi skor terhadap maksimum 1.
        Ini satu-satunya tempat di halaman analitik yang memakai warna status
        sebagai isian, supaya tiga kartu lain tidak ikut berwarna-warni.
      */}
      {progress !== null ? (
        <div className="absolute inset-x-0 bottom-0 h-1 bg-muted" aria-hidden>
          <div
            className={cn("h-full", TONE_BAR[tone])}
            style={{ width: `${Math.max(0, Math.min(1, progress)) * 100}%` }}
          />
        </div>
      ) : null}
    </div>
  );
}
