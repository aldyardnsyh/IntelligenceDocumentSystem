import type { Metadata } from "next";
import { AnalyticsView } from "@/components/analytics/analytics-view";

export const metadata: Metadata = {
  title: "Evaluasi & Observability",
  description: "Skor RAGAS, tren latensi, dan log query.",
};

export default function AnalyticsPage() {
  return (
    <div className="mx-auto flex w-full max-w-[1200px] flex-1 flex-col px-4 py-8 sm:px-6">
      <AnalyticsView />
    </div>
  );
}
