"use client";

import { useState } from "react";
import * as React from "react";
import { Dialog as DialogPrimitive } from "@base-ui/react/dialog";
import { Loader2, TriangleAlert } from "lucide-react";
import { cn } from "cn";
import { Button } from "@/components/ui/button";

interface ConfirmDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  description: string;
  /** Baris detail monospace, misalnya "7 dokumen · 148 chunk". */
  detail?: string;
  confirmLabel: string;
  cancelLabel?: string;
  onConfirm: () => Promise<void> | void;
  className?: string;
}

/**
 * Konfirmasi untuk aksi yang tidak bisa dibatalkan (hapus dokumen, reset
 * semua sesi). Sengaja modal, bukan toast: pengguna harus berhenti dan membaca
 * konsekuensinya dulu.
 */
export function ConfirmDialog({
  open,
  onOpenChange,
  title,
  description,
  detail,
  confirmLabel,
  cancelLabel = "Batal",
  onConfirm,
  className,
}: ConfirmDialogProps) {
  const [busy, setBusy] = useState(false);

  const handleConfirm = async () => {
    setBusy(true);
    try {
      await onConfirm();
      onOpenChange(false);
    } finally {
      setBusy(false);
    }
  };

  return (
    <DialogPrimitive.Root open={open} onOpenChange={onOpenChange}>
      <DialogPrimitive.Portal>
        <DialogPrimitive.Backdrop
          className={cn(
            "fixed inset-0 z-50 bg-black/30 transition-opacity duration-150",
            "data-starting-style:opacity-0 data-ending-style:opacity-0",
          )}
        />
        <DialogPrimitive.Popup
          className={cn(
            "fixed top-1/2 left-1/2 z-50 w-[calc(100vw-2rem)] max-w-md -translate-x-1/2 -translate-y-1/2",
            "rounded-lg bg-card p-6 shadow-xl ring-1 ring-border",
            "transition-all duration-150 data-starting-style:scale-95 data-starting-style:opacity-0",
            "data-ending-style:scale-95 data-ending-style:opacity-0",
            className,
          )}
        >
          <div className="flex items-start gap-3">
            <span className="mt-0.5 flex size-8 shrink-0 items-center justify-center rounded-lg bg-destructive/10 text-destructive">
              <TriangleAlert className="size-4" aria-hidden />
            </span>
            <div className="flex min-w-0 flex-col gap-1.5">
              <DialogPrimitive.Title className="text-[15px] font-semibold">
                {title}
              </DialogPrimitive.Title>
              <DialogPrimitive.Description className="text-[13px] leading-relaxed text-muted-foreground">
                {description}
              </DialogPrimitive.Description>
              {detail ? (
                <p className="mt-1 rounded-md bg-muted px-3 py-2 font-mono text-[12px] text-foreground/80">
                  {detail}
                </p>
              ) : null}
            </div>
          </div>

          <div className="mt-6 flex justify-end gap-2">
            <Button variant="outline" onClick={() => onOpenChange(false)} disabled={busy}>
              {cancelLabel}
            </Button>
            <Button variant="destructive" onClick={handleConfirm} disabled={busy} className="gap-1.5">
              {busy ? <Loader2 className="size-4 animate-spin" aria-hidden /> : null}
              {confirmLabel}
            </Button>
          </div>
        </DialogPrimitive.Popup>
      </DialogPrimitive.Portal>
    </DialogPrimitive.Root>
  );
}
