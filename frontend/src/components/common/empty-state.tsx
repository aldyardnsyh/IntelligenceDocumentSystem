import type { LucideIcon } from "lucide-react";

interface EmptyStateProps {
  Icon: LucideIcon;
  title: string;
  description: string;
  /** Satu aksi utama. Tanpa aksi, komponen ini hanya menjelaskan, tidak menjanjikan. */
  action?: React.ReactNode;
  className?: string;
}

/**
 * Empty state selalu menyebut penyebab dan langkah berikutnya. "No data" tanpa
 * arahan membuat pengguna menebak apa yang salah.
 */
export function EmptyState({ Icon, title, description, action, className }: EmptyStateProps) {
  return (
    <div
      className={`flex flex-col items-center gap-3 rounded-lg border border-dashed border-border px-6 py-10 text-center ${className ?? ""}`}
    >
      <span className="flex size-10 items-center justify-center rounded-lg bg-muted text-muted-foreground">
        <Icon className="size-5" aria-hidden />
      </span>
      <div className="flex flex-col gap-1">
        <p className="text-[15px] font-semibold">{title}</p>
        <p className="max-w-md text-[13px] leading-relaxed text-muted-foreground">{description}</p>
      </div>
      {action}
    </div>
  );
}
