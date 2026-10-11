"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { LineChart as LineChartIcon } from "lucide-react";
import { toast } from "sonner";
import { EmptyState } from "@/components/common/empty-state";
import { ErrorState } from "@/components/common/error-state";
import { ChartSkeleton, StatCardSkeleton } from "@/components/common/skeletons";
import { LatencyChart, TokenChart } from "./charts";
import { EvaluationSetup } from "./evaluation-setup";
import { QueryLogTable } from "./query-log-table";
import { StatCard, type StatTone } from "./stat-card";
import { getAnalyticsSummary, runRetrievalEvaluation } from "@/lib/api";
import { ApiError } from "@/lib/api/error";
import { queryKeys, useDocuments } from "@/lib/queries";

/** Ambang target dari PRD Section 1.3. */
const TARGETS = {
  precision: 0.75,
  answer_relevance: 0.8,
  faithfulness: 0.75,
} as const;

function toneForScore(value: number, target: number): StatTone {
  if (value >= target) return "success";
  if (value >= target - 0.05) return "warning";
  return "error";
}

export function AnalyticsView() {
  const queryClient = useQueryClient();
  const documents = useDocuments();
  // Hanya dokumen siap yang bisa diuji; yang masih diproses akan
  // ditolak server, dan itu pesan error yang tidak perlu ditampilkan.
  const readyDocuments = (documents.data ?? []).filter(
    (item) => item.status === "ready",
  );
  const summary = useQuery({
    queryKey: queryKeys.analyticsSummary,
    queryFn: ({ signal }) => getAnalyticsSummary(signal),
    refetchInterval: 30_000,
  });

  /**
   * Jalankan evaluasi retrieval langsung dari halaman ini.
   *
   * Sebelumnya halaman hanya menampilkan "belum ada data evaluasi" dan
   * menyuruh menjalankan job lewat CLI, tanpa memberi tahu caranya, dan
   * tanpa jalan keluar kalau kredensial RAGAS belum ada. Evaluasi ini tidak
   * butuh LLM, jadi selalu bisa dijalankan.
   */
  const evaluate = useMutation({
    mutationFn: (documentIds: string[]) => runRetrievalEvaluation(documentIds),
    onSuccess: (run) => {
      queryClient.invalidateQueries({ queryKey: queryKeys.analyticsSummary });
      toast.success(
        `Evaluasi selesai. Precision ${run.precision?.toFixed(2) ?? "-"}, `
        + `hit rate ${run.answer_relevance?.toFixed(2) ?? "-"}.`,
      );
    },
    onError: (error) => {
      toast.error(
        error instanceof ApiError ? error.message : "Evaluasi gagal dijalankan.",
      );
    },
  });

  if (summary.isPending) {
    return (
      <div className="flex flex-col gap-4">
        <StatCardSkeleton />
        <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
          <ChartSkeleton />
          <ChartSkeleton />
        </div>
      </div>
    );
  }

  if (summary.isError) {
    return <ErrorState error={summary.error} onRetry={() => summary.refetch()} />;
  }

  const data = summary.data;
  const evalRun = data.latest_eval;
  const hasLatency = data.latency.length > 0;
  const hasTokens = data.tokens.length > 0;

  return (
    <div className="flex flex-col gap-6">
      <header className="flex flex-col gap-1.5">
        <p className="eyebrow">Evaluasi dan observability</p>
        <h1 className="text-2xl font-semibold tracking-tight">Evaluasi &amp; Observability</h1>
        <p className="max-w-2xl text-[13px] leading-relaxed text-muted-foreground">
          Skor kualitas retrieval, jejak latensi, dan log query. Semua angka di
          halaman ini berasal dari pengukuran yang benar-benar tercatat, tidak
          ada nilai contoh.
        </p>
      </header>

      {/*
        Area kartu statistik memakai RAGAS. Kalau belum ada run evaluasi,
        kartu diganti empty state yang menjelaskan cara mengisinya, bukan
        diisi angka placeholder (TC-12).
      */}
      {evalRun ? (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
          {evalRun.precision !== null ? (
            <StatCard
              label="Precision"
              value={evalRun.precision.toFixed(2)}
              helper={`Ambang target ${TARGETS.precision.toFixed(2)}`}
              tone={toneForScore(evalRun.precision, TARGETS.precision)}
              progress={evalRun.precision}
            />
          ) : null}
          {evalRun.answer_relevance !== null ? (
            <StatCard
              label="Answer relevance"
              value={evalRun.answer_relevance.toFixed(2)}
              helper={`Ambang target ${TARGETS.answer_relevance.toFixed(2)}`}
              tone={toneForScore(evalRun.answer_relevance, TARGETS.answer_relevance)}
              progress={evalRun.answer_relevance}
            />
          ) : null}
          {evalRun.faithfulness !== null ? (
            <StatCard
              label="Faithfulness"
              value={evalRun.faithfulness.toFixed(2)}
              helper={`Ambang target ${TARGETS.faithfulness.toFixed(2)}`}
              tone={toneForScore(evalRun.faithfulness, TARGETS.faithfulness)}
              progress={evalRun.faithfulness}
            />
          ) : null}
        </div>
      ) : (
        <EvaluationSetup
          documents={readyDocuments}
          isLoading={documents.isPending}
          pending={evaluate.isPending}
          onRun={(ids) => evaluate.mutate(ids)}
        />
      )}

      {/*
        Skor RAGAS (faithfulness, answer relevance) butuh LLM penilai dan
        kredensial tambahan. Dijelaskan di sini supaya pengguna tahu metrik
        mana yang belum ada dan kenapa, bukan dibiarkan mengira angkanya
        hilang.
      */}
      {evalRun && evalRun.faithfulness === null ? (
        <p className="rounded-lg border border-border bg-muted/40 px-4 py-3 text-[12px] leading-relaxed text-muted-foreground">
          Skor <span className="font-medium">faithfulness</span> belum ada:
          metrik itu dinilai oleh LLM kedua dan butuh kredensial evaluator
          (<code className="font-mono">OPENAI_API_KEY</code>). Jalankan{" "}
          <code className="font-mono">python -m scripts.evaluate_ragas</code>{" "}
          setelah kredensial tersedia untuk melengkapinya. Angka di atas
          dihitung tanpa LLM, jadi tidak memerlukan kredensial apa pun.
        </p>
      ) : null}

      {hasLatency || hasTokens ? (
        <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
          {hasLatency ? <LatencyChart data={data.latency} /> : null}
          {hasTokens ? <TokenChart data={data.tokens} /> : null}
        </div>
      ) : null}

      {!hasLatency && !hasTokens ? (
        <EmptyState
          Icon={LineChartIcon}
          title="Belum ada jejak latensi"
          description="Grafik muncul setelah ada query yang tercatat. Ajukan satu pertanyaan di halaman chat, lalu kembali ke sini."
        />
      ) : null}

      <QueryLogTable />
    </div>
  );
}
