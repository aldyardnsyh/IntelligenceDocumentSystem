"use client";

import { useRef, useState } from "react";
import * as React from "react";
import { Dialog as DialogPrimitive } from "@base-ui/react/dialog";
import { Loader2 } from "lucide-react";
import { cn } from "cn";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

interface RenameSessionDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  currentTitle: string;
  maxLength: number;
  onSubmit: (title: string) => Promise<void> | void;
}

/**
 * Isi form, dipisah dari shell dialog.
 *
 * State form di sini diinisialisasi sekali dari `initialValue` saat mount,
 * lalu mengikuti keystroke pengguna. Pemeriksaan ulang tidak dilakukan setiap
 * render, karena bentuk form memang sama; yang berubah hanya isinya.
 *
 * Dialog jaminan mengisi ulang form saat dibuka lagi untuk sesi lain adalah
 * soal `key` pada pemanggil. Dengan begitu tidak ada effect yang perlu
 * menulis state, dan form tidak pernah sempat menampilkan judul sesi
 * sebelumnya.
 */
function RenameForm({
  initialValue,
  maxLength,
  onSubmit,
  onCancel,
}: {
  initialValue: string;
  maxLength: number;
  onSubmit: (title: string) => Promise<void>;
  onCancel: () => void;
}) {
  const [value, setValue] = useState(initialValue);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const submit = async () => {
    const trimmed = value.trim().replace(/\s+/g, " ");
    if (trimmed.length === 0) {
      setError("Nama sesi tidak boleh kosong.");
      return;
    }
    if (trimmed.length > maxLength) {
      setError(`Nama sesi maksimal ${maxLength} karakter.`);
      return;
    }

    setBusy(true);
    setError(null);
    try {
      await onSubmit(trimmed);
    } catch (submitError) {
      setError(
        submitError instanceof Error ? submitError.message : "Gagal menyimpan nama sesi.",
      );
      setBusy(false);
    }
  };

  return (
    <form
      className="mt-5 flex flex-col gap-2"
      onSubmit={(event) => {
        event.preventDefault();
        void submit();
      }}
    >
      <Label htmlFor="session-title" className="text-[13px] font-medium">
        Nama percakapan
      </Label>
      <Input
        ref={inputRef}
        // autoFocus lebih tepat daripada select() di dalam effect: field-nya
        // langsung siap diketik begitu dialog muncul, tanpa satu frame tanpa
        // sorotan teks.
        autoFocus
        id="session-title"
        value={value}
        onChange={(event) => {
          setValue(event.target.value);
          if (error) setError(null);
        }}
        maxLength={maxLength}
        disabled={busy}
        aria-invalid={error !== null}
        aria-describedby="session-title-feedback"
      />
      <p
        id="session-title-feedback"
        className={cn("min-h-5 text-[12px]", error ? "text-destructive" : "text-muted-foreground")}
      >
        {error ?? `${value.length} / ${maxLength} karakter`}
      </p>

      <div className="mt-2 flex justify-end gap-2">
        <Button type="button" variant="outline" onClick={onCancel} disabled={busy}>
          Batal
        </Button>
        <Button type="submit" disabled={busy || value.trim().length === 0} className="gap-1.5">
          {busy ? <Loader2 className="size-4 animate-spin" aria-hidden /> : null}
          Simpan
        </Button>
      </div>
    </form>
  );
}

/**
 * Ubah nama sesi.
 *
 * Modal, bukan inline edit: nama ini muncul di sidebar sekaligus di judul
 * halaman, jadi mengeditnya di tempat tidak akan terasa sebagai perubahan
 * yang benar-benar tersimpan.
 */
export function RenameSessionDialog({
  open,
  onOpenChange,
  currentTitle,
  maxLength,
  onSubmit,
}: RenameSessionDialogProps) {
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
          )}
        >
          <div className="flex flex-col gap-1.5">
            <DialogPrimitive.Title className="text-[15px] font-semibold">
              Ubah nama percakapan
            </DialogPrimitive.Title>
            <DialogPrimitive.Description className="text-[13px] leading-relaxed text-muted-foreground">
              Nama ini hanya untuk membedakan percakapan di sidebar. Isi
              jawabannya tidak berubah.
            </DialogPrimitive.Description>
          </div>

          {open ? (
            <RenameForm
              // `key` ditulis oleh pemanggil lewat pemanggilan ulang komponen
              // ini, jadi form baru dibuat setiap kali dialog dibuka.
              initialValue={currentTitle}
              maxLength={maxLength}
              onSubmit={async (title) => {
                await onSubmit(title);
                onOpenChange(false);
              }}
              onCancel={() => onOpenChange(false)}
            />
          ) : null}
        </DialogPrimitive.Popup>
      </DialogPrimitive.Portal>
    </DialogPrimitive.Root>
  );
}
