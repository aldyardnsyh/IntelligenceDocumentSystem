"use client";

import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip as RechartsTooltip,
  XAxis,
  YAxis,
} from "recharts";
import { formatDay, formatDuration, formatNumber } from "@/lib/format";
import type { LatencyPoint, TokenPoint } from "@/types/api";

const AXIS_STYLE = {
  fontSize: 11,
  fill: "var(--muted-foreground)",
} as const;

const TOOLTIP_STYLE = {
  background: "var(--popover)",
  border: "1px solid var(--border)",
  borderRadius: 8,
  fontSize: 12,
  color: "var(--popover-foreground)",
  boxShadow: "0 4px 16px rgb(0 0 0 / 0.08)",
} as const;

/** Recharts mengoper tipe longgar ke formatter, jadi nilainya dibueroleh dulu. */
function labelOf(label: unknown): string {
  return formatDay(String(label));
}

function toNumber(value: unknown): number {
  return typeof value === "number" ? value : Number(value ?? 0);
}

/**
 * Judul chart selalu berupa pertanyaan yang dijawab chart itu, bukan
 * "Overview" atau "Performa" (C-3). Kalau jawabannya lebih ringkas berupa
 * satu kalimat, chart tidak perlu ada.
 */
export function LatencyChart({ data }: { data: LatencyPoint[] }) {
  return (
    <div className="flex flex-col gap-3 rounded-lg bg-card p-5 ring-1 ring-border">
      <div className="flex flex-col gap-1">
        <h3 className="text-[15px] font-semibold">
          Seberapa lama menjawab satu pertanyaan?
        </h3>
        <p className="text-[12px] text-muted-foreground">
          Rata-rata dan persentil 95 waktu respons, dihitung dari log query yang
          benar-benar tercatat.
        </p>
      </div>
      <div className="h-[240px] w-full">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: -12 }}>
            <CartesianGrid stroke="var(--border)" vertical={false} />
            <XAxis dataKey="date" tickFormatter={formatDay} tick={AXIS_STYLE} axisLine={false} tickLine={false} />
            <YAxis
              tick={AXIS_STYLE}
              axisLine={false}
              tickLine={false}
              tickFormatter={(value: number) => formatDuration(value)}
              width={56}
            />
            <RechartsTooltip
              contentStyle={TOOLTIP_STYLE}
              labelFormatter={labelOf}
              formatter={(value, name) => [
                formatDuration(toNumber(value)),
                name === "avg_ms" ? "Rata-rata" : "p95",
              ]}
            />
            <Legend
              formatter={(value) => (value === "avg_ms" ? "Rata-rata" : "p95")}
              wrapperStyle={{ fontSize: 12, paddingTop: 8 }}
            />
            <Line
              type="monotone"
              dataKey="avg_ms"
              stroke="var(--chart-1)"
              strokeWidth={2}
              dot={{ r: 3, fill: "var(--card)", stroke: "var(--chart-1)", strokeWidth: 2 }}
              activeDot={{ r: 5 }}
            />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

export function TokenChart({ data }: { data: TokenPoint[] }) {
  const total = data.reduce(
    (sum, point) => sum + point.input_tokens + point.output_tokens,
    0,
  );

  return (
    <div className="flex flex-col gap-3 rounded-lg bg-card p-5 ring-1 ring-border">
      <div className="flex items-start justify-between gap-3">
        <div className="flex flex-col gap-1">
          <h3 className="text-[15px] font-semibold">
            Berapa token yang terpakai untuk menjawab?
          </h3>
          <p className="text-[12px] text-muted-foreground">
            Token input (pertanyaan dan konteks retrieval) dibanding token output
            (jawaban). Angka ini{" "}
            <span className="text-warning-ink">
              estimasi dari panjang pertanyaan, bukan hitungan penyedia
            </span>{" "}
           , pakai untuk melihat tren, bukan untuk tagihan.
          </p>
        </div>
        {total > 0 ? (
          <span className="shrink-0 font-mono text-[12px] text-muted-foreground tnum">
            total {formatNumber(total)}
          </span>
        ) : null}
      </div>
      <div className="h-[240px] w-full">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: -12 }}>
            <CartesianGrid stroke="var(--border)" vertical={false} />
            <XAxis dataKey="date" tickFormatter={formatDay} tick={AXIS_STYLE} axisLine={false} tickLine={false} />
            <YAxis tick={AXIS_STYLE} axisLine={false} tickLine={false} width={48} />
            <RechartsTooltip
              contentStyle={TOOLTIP_STYLE}
              labelFormatter={labelOf}
              formatter={(value, name) => [
                formatNumber(toNumber(value)),
                name === "input_tokens" ? "Input" : "Output",
              ]}
            />
            <Legend
              formatter={(value) => (value === "input_tokens" ? "Input" : "Output")}
              wrapperStyle={{ fontSize: 12, paddingTop: 8 }}
            />
            <Bar dataKey="input_tokens" stackId="tokens" fill="var(--chart-1)" radius={[0, 0, 0, 0]} />
            <Bar
              dataKey="output_tokens"
              stackId="tokens"
              fill="var(--chart-2)"
              radius={[3, 3, 0, 0]}
            />
          </BarChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
