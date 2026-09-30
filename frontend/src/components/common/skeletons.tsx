import { Skeleton } from "@/components/ui/skeleton";

/**
 * Skeleton mengikuti bentuk konten asli, bukan kotak abu generik, supaya
 * tidak ada "lompatan" saat data datang (design.md 10).
 */

export function SessionListSkeleton({ rows = 4 }: { rows?: number }) {
  const widths = ["w-[80%]", "w-[60%]", "w-[70%]", "w-[52%]", "w-[66%]"];
  return (
    <ul className="flex flex-col gap-2" aria-hidden>
      {Array.from({ length: rows }, (_, index) => (
        <li key={index} className="rounded-lg px-3 py-2.5">
          <Skeleton className={`h-3 ${widths[index % widths.length]}`} />
          <Skeleton className="mt-2 h-2.5 w-[40%]" />
        </li>
      ))}
    </ul>
  );
}

export function DocumentCardSkeleton() {
  return (
    <div className="flex flex-col gap-3 rounded-lg bg-card p-4 ring-1 ring-border" aria-hidden>
      <div className="flex items-center gap-2.5">
        <Skeleton className="size-8 rounded-md" />
        <Skeleton className="h-3.5 w-[55%]" />
      </div>
      <Skeleton className="h-2.5 w-[35%]" />
      <Skeleton className="h-5 w-24 rounded-full" />
    </div>
  );
}

export function DocumentGridSkeleton({ count = 3 }: { count?: number }) {
  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-3" aria-hidden>
      {Array.from({ length: count }, (_, index) => (
        <DocumentCardSkeleton key={index} />
      ))}
    </div>
  );
}

export function MessageSkeleton() {
  return (
    <div className="flex w-full flex-col gap-6" aria-hidden>
      {[0, 1, 2].map((index) => (
        <div key={index} className={index % 2 === 0 ? "flex justify-end" : "flex justify-start"}>
          <div
            className={`rounded-2xl ${index % 2 === 0 ? "w-[62%]" : "w-[78%]"} ${
              index % 2 === 0 ? "bg-primary/10" : "bg-card ring-1 ring-border"
            } flex flex-col gap-2 p-4`}
          >
            <Skeleton className="h-3 w-full" />
            <Skeleton className="h-3 w-[92%]" />
            <Skeleton className="h-3 w-[70%]" />
          </div>
        </div>
      ))}
    </div>
  );
}

export function CitationSkeleton() {
  return (
    <div className="mt-3 flex w-full max-w-sm flex-col gap-2 rounded-lg border border-border p-3" aria-hidden>
      <Skeleton className="h-3 w-[45%]" />
      <Skeleton className="h-2.5 w-full" />
    </div>
  );
}

export function ChunkListSkeleton({ count = 5 }: { count?: number }) {
  return (
    <div className="rounded-lg bg-card ring-1 ring-border" aria-hidden>
      {Array.from({ length: count }, (_, index) => (
        <div key={index} className="flex flex-col gap-2 border-b border-border px-4 py-3 last:border-b-0">
          <Skeleton className="h-3.5 w-[28%]" />
          <Skeleton className="h-2.5 w-[62%]" />
        </div>
      ))}
    </div>
  );
}

export function StatCardSkeleton({ count = 3 }: { count?: number }) {
  return (
    <div className="grid grid-cols-1 gap-4 md:grid-cols-3" aria-hidden>
      {Array.from({ length: count }, (_, index) => (
        <div key={index} className="flex flex-col gap-3 rounded-lg bg-card p-5 ring-1 ring-border">
          <Skeleton className="h-2.5 w-[45%]" />
          <Skeleton className="h-8 w-[38%]" />
          <Skeleton className="h-2.5 w-[65%]" />
        </div>
      ))}
    </div>
  );
}

export function ChartSkeleton() {
  return (
    <div className="flex flex-col gap-3 rounded-lg bg-card p-5 ring-1 ring-border" aria-hidden>
      <Skeleton className="h-3.5 w-[40%]" />
      <Skeleton className="h-2.5 w-[60%]" />
      <Skeleton className="h-[240px] w-full rounded-md" />
    </div>
  );
}

export function TableSkeleton({ rows = 5 }: { rows?: number }) {
  return (
    <div className="flex flex-col gap-2 rounded-lg bg-card p-4 ring-1 ring-border" aria-hidden>
      <Skeleton className="h-3 w-[28%]" />
      {Array.from({ length: rows }, (_, index) => (
        <div key={index} className="flex items-center gap-4">
          <Skeleton className="h-3 w-[30%]" />
          <Skeleton className="h-3 w-[20%]" />
          <Skeleton className="h-3 w-[12%]" />
        </div>
      ))}
    </div>
  );
}
