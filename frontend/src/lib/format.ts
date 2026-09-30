/**
 * Format tanggal.
 *
 * Server selalu mengirim UTC. Formatting dilakukan dengan zona waktu browser
 * pengguna, di satu tempat ini saja, supaya sumbu chart, timestamp di log, dan
 * waktu unggah tidak pernah berbeda tanggal karena masing-masing punya
 * formatter sendiri.
 */

const UNITS = ["B", "KB", "MB", "GB"];

export function formatBytes(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes <= 0) return "0 B";
  const exponent = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), UNITS.length - 1);
  const value = bytes / 1024 ** exponent;
  return `${value.toFixed(value >= 10 || exponent === 0 ? 0 : 1)} ${UNITS[exponent]}`;
}

const RELATIVE_STEPS: Array<[
  limitSeconds: number,
  divisor: number,
  unit: Intl.RelativeTimeFormatUnit,
]> = [
  [60, 1, "second"],
  [3600, 60, "minute"],
  [86_400, 3600, "hour"],
  [604_800, 86_400, "day"],
  [2_629_800, 604_800, "week"],
  [31_557_600, 2_629_800, "month"],
];

const relativeFormatter = new Intl.RelativeTimeFormat("id-ID", { numeric: "auto" });

export function formatRelative(iso: string): string {
  const timestamp = Date.parse(iso);
  if (Number.isNaN(timestamp)) return "-";

  const deltaSeconds = (timestamp - Date.now()) / 1000;
  const absolute = Math.abs(deltaSeconds);

  for (const [limit, divisor, unit] of RELATIVE_STEPS) {
    if (absolute < limit) {
      return relativeFormatter.format(Math.round(deltaSeconds / divisor), unit);
    }
  }
  return relativeFormatter.format(Math.round(deltaSeconds / 31_557_600), "year");
}

const dateTimeFormatter = new Intl.DateTimeFormat("id-ID", {
  dateStyle: "medium",
  timeStyle: "short",
});

/** `2026-09-29T02:15:00Z` -> "29 Sep 2026, 09.15" dalam waktu lokal pengguna. */
export function formatDateTime(iso: string): string {
  const timestamp = Date.parse(iso);
  if (Number.isNaN(timestamp)) return "-";
  return dateTimeFormatter.format(new Date(timestamp));
}

const dayFormatter = new Intl.DateTimeFormat("id-ID", {
  weekday: "short",
  day: "numeric",
});

/** Bucket tanggal harian dari server (`YYYY-MM-DD`, UTC) -> "Sen, 28". */
export function formatDay(value: string): string {
  const timestamp = Date.parse(value.includes("T") ? value : `${value}T00:00:00Z`);
  if (Number.isNaN(timestamp)) return value;
  return dayFormatter.format(new Date(timestamp));
}

export function formatDuration(ms: number): string {
  if (!Number.isFinite(ms)) return "-";
  if (ms < 1000) return `${Math.round(ms)} ms`;
  return `${(ms / 1000).toFixed(ms < 10_000 ? 2 : 1)} s`;
}

export function formatNumber(value: number): string {
  return new Intl.NumberFormat("id-ID").format(value);
}

/** Skor kemiripan 0..1 -> "94%". */
export function formatPercent(value: number): string {
  return `${Math.round(value * 100)}%`;
}

/** Memotong nama berkas di tengah supaya ekstensi tetap terbaca. */
export function truncateMiddle(value: string, max = 34): string {
  if (value.length <= max) return value;
  const head = Math.ceil((max - 1) / 2);
  const tail = Math.floor((max - 1) / 2);
  return `${value.slice(0, head)}...${value.slice(value.length - tail)}`;
}
