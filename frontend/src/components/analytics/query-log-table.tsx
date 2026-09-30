"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ChevronLeft, ChevronRight, Download, Inbox, Search } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { EmptyState } from "@/components/common/empty-state";
import { ErrorState } from "@/components/common/error-state";
import { TableSkeleton } from "@/components/common/skeletons";
import { getAnalyticsLogs } from "@/lib/api";
import { queryKeys } from "@/lib/queries";
import { externalLinks } from "@/lib/api/config";
import { formatDuration, formatRelative } from "@/lib/format";
import type { QueryLog } from "@/types/api";

const PAGE_SIZE = 10;

/**
 * Id trace hanya jadi tautan kalau ada env URL tracing. Tanpa itu, id tetap
 * ditampilkan sebagai teks monospace: nilainya berguna untuk dicari di
 * Langfuse, dan mengarang URL tujuan hanya menambah satu klik yang gagal.
 */
function TraceCell({ traceId }: { traceId: string | null }) {
  if (!traceId) {
    return (
      <span className="text-[12px] text-muted-foreground" title="Tidak ada panggilan LLM untuk query ini">
        -
      </span>
    );
  }

  if (!externalLinks.tracing) {
    return <span className="font-mono text-[11px] text-muted-foreground">{traceId}</span>;
  }

  return (
    <a
      href={`${externalLinks.tracing.replace(/\/+$/, "")}/api/public/traces/${encodeURIComponent(traceId)}`}
      target="_blank"
      rel="noreferrer"
      className="rounded font-mono text-[11px] text-brand-ink underline underline-offset-2 hover:no-underline"
    >
      {traceId}
    </a>
  );
}

export function QueryLogTable() {
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState("");

  const logs = useQuery({
    queryKey: queryKeys.analyticsLogs(page),
    queryFn: ({ signal }) => getAnalyticsLogs(page, PAGE_SIZE, signal),
  });

  const items = logs.data?.items ?? [];
  const total = logs.data?.total ?? 0;
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const term = search.trim().toLowerCase();
  const visible = term.length === 0
    ? items
    : items.filter((item) => item.question.toLowerCase().includes(term));

  return (
    <section className="flex flex-col gap-3 rounded-lg bg-card p-5 ring-1 ring-border">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div className="flex flex-col gap-1">
          <h3 className="text-[15px] font-semibold">Log interaksi terakhir</h3>
          <p className="text-[12px] text-muted-foreground">
            Setiap baris adalah satu pertanyaan nyata beserta durasi dan jumlah
            sumber yang ditemukan.
          </p>
        </div>
        <div className="relative sm:w-60">
          <Search
            className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted-foreground"
            aria-hidden
          />
          <Input
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="Cari pertanyaan"
            aria-label="Cari pertanyaan pada log"
            className="pl-9"
          />
        </div>
      </div>

      {logs.isError ? (
        <ErrorState error={logs.error} onRetry={() => logs.refetch()} title="Log gagal dimuat" />
      ) : logs.isPending ? (
        <TableSkeleton />
      ) : items.length === 0 ? (
        <EmptyState
          Icon={Inbox}
          title="Belum ada query tercatat"
          description="Log terisi otomatis saat Anda mengirim pertanyaan pertama di halaman chat. Tidak ada data contoh yang ditampilkan di sini."
        />
      ) : visible.length === 0 ? (
        <EmptyState
          Icon={Search}
          title="Tidak ada baris yang cocok"
          description={`Tidak ada pertanyaan pada halaman ini yang mengandung "${search.trim()}".`}
          action={
            <Button variant="outline" size="sm" className="mt-1" onClick={() => setSearch("")}>
              Hapus pencarian
            </Button>
          }
        />
      ) : (
        <>
          <div className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Pertanyaan</TableHead>
                  <TableHead className="text-right">Waktu respons</TableHead>
                  <TableHead className="text-right">Sumber</TableHead>
                  <TableHead>Trace</TableHead>
                  <TableHead className="text-right">Waktu</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {visible.map((item) => (
                  <TableRow key={item.id}>
                    <TableCell className="max-w-[420px]">
                      <span className="line-clamp-2">{item.question}</span>
                    </TableCell>
                    <TableCell className="text-right font-mono text-[12px] tnum">
                      {formatDuration(item.response_time_ms)}
                    </TableCell>
                    <TableCell className="text-right tnum">
                      {item.sources_count === 0 ? (
                        <span className="text-warning-ink">tidak ditemukan</span>
                      ) : (
                        item.sources_count
                      )}
                    </TableCell>
                    <TableCell>
                      <TraceCell traceId={item.trace_id} />
                    </TableCell>
                    <TableCell className="text-right text-[12px] text-muted-foreground">
                      {formatRelative(item.created_at)}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>

          <div className="flex flex-wrap items-center justify-between gap-3 border-t border-border pt-3">
            <p className="text-[12px] text-muted-foreground tnum">
              Menampilkan {visible.length} dari {total} query
            </p>
            <div className="flex items-center gap-2">
              <ExportLogsButton rows={visible} />
              <div className="flex items-center gap-1">
                <Button
                  variant="outline"
                  size="icon-sm"
                  disabled={page <= 1}
                  onClick={() => setPage((value) => Math.max(1, value - 1))}
                  aria-label="Halaman sebelumnya"
                >
                  <ChevronLeft className="size-4" aria-hidden />
                </Button>
                <span className="px-2 text-[12px] tnum">
                  {page} / {totalPages}
                </span>
                <Button
                  variant="outline"
                  size="icon-sm"
                  disabled={page >= totalPages}
                  onClick={() => setPage((value) => Math.min(totalPages, value + 1))}
                  aria-label="Halaman berikutnya"
                >
                  <ChevronRight className="size-4" aria-hidden />
                </Button>
              </div>
            </div>
          </div>
        </>
      )}
    </section>
  );
}

/**
 * Ekspor memakai data yang sedang tampil, jadi isinya tidak pernah berbeda
 * dari tabel di atasnya. Tidak ada tombol unduh yang tidak mengunduh apa pun.
 */
function ExportLogsButton({ rows }: { rows: QueryLog[] }) {
  const handleExport = () => {
    const blob = new Blob([JSON.stringify(rows, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `query-log-${new Date().toISOString().slice(0, 10)}.json`;
    anchor.click();
    URL.revokeObjectURL(url);
  };

  return (
    <Button variant="outline" size="sm" onClick={handleExport} className="gap-1.5">
      <Download className="size-3.5" aria-hidden />
      Ekspor JSON
    </Button>
  );
}
