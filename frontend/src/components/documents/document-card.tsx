"use client";

import { useRef, useState } from "react";
import Link from "next/link";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { FileText, MoreHorizontal, RotateCw, Trash2 } from "lucide-react";
import { notify } from "@/lib/notify";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { ConfirmDialog } from "@/components/common/confirm-dialog";
import { deleteDocument, uploadDocument } from "@/lib/api";
import { queryKeys } from "@/lib/queries";
import { ApiError } from "@/lib/api/error";
import { formatBytes, formatRelative } from "@/lib/format";
import type { DocumentStatus, DocumentSummary } from "@/types/api";

/**
 * Satu komponen ini memegang pemetaan status untuk semua keadaan dokumen,
 * jadi warna badge tidak pernah berarti dua hal berbeda di halaman berbeda.
 * Badge hanya dipakai kalau fungsinya nyata, yaitu status.
 */
const STATUS_META: Record<
  DocumentStatus,
  { label: string; className: string; dot: string; busy?: boolean }
> = {
  uploading: {
    label: "Mengunggah...",
    className: "bg-muted text-muted-foreground",
    dot: "bg-muted-foreground",
    busy: true,
  },
  processing: {
    label: "Memproses...",
    className: "bg-warning/10 text-warning-ink",
    dot: "bg-warning animate-pulse",
    busy: true,
  },
  ready: {
    label: "Siap ditanyai",
    className: "bg-success/10 text-success-ink",
    dot: "bg-success",
  },
  failed: {
    label: "Gagal diproses",
    className: "bg-destructive/10 text-destructive",
    dot: "bg-destructive",
  },
};

export function DocumentStatusBadge({ status }: { status: DocumentStatus }) {
  const meta = STATUS_META[status];
  return (
    <Badge variant="secondary" className={`gap-1.5 ${meta.className}`}>
      <span className={`size-1.5 rounded-full ${meta.dot}`} aria-hidden />
      {meta.label}
    </Badge>
  );
}

interface DocumentCardProps {
  document: DocumentSummary;
}

export function DocumentCard({ document }: DocumentCardProps) {
  const queryClient = useQueryClient();
  const [confirmOpen, setConfirmOpen] = useState(false);

  const removeMutation = useMutation({
    mutationFn: () => deleteDocument(document.id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.documents });
      notify.success(
        "Dokumen dihapus",
        `"${document.filename}" beserta seluruh chunk dan indeksnya sudah dibuang.`,
      );
    },
    onError: (error) => {
      notify.error(error instanceof ApiError ? error.message : "Dokumen gagal dihapus. Coba lagi.",)
    },
  });

  // berkas asli sudah tidak ada di browser, jadi "coba lagi" berarti
  // meminta pengguna memilih ulang berkasnya. Tidak ada tombol yang berpura-pura
  // mengunggah ulang sesuatu yang tidak ada.
  const retryInputRef = useRef<HTMLInputElement>(null);
  const retryMutation = useMutation({
    mutationFn: (file: File) => uploadDocument(file),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.documents });
      notify.success(
        "Dokumen dikirim ulang",
        "Ingestion berjalan lagi di server. Tunggu status berubah menjadi Siap ditanyai.",
      );
    },
    onError: (error) => {
      notify.error(error instanceof ApiError ? error.message : "Gagal mengunggah ulang.")
    },
  });

  const failed = document.status === "failed";
  const busy = STATUS_META[document.status].busy;

  return (
    <>
      <div className="group relative flex flex-col gap-3 rounded-lg bg-card p-4 ring-1 ring-border transition-shadow hover:shadow-sm">
        <div className="flex items-start gap-2.5">
          <span className="mt-0.5 flex size-8 shrink-0 items-center justify-center rounded-md bg-muted text-muted-foreground">
            <FileText className="size-4" aria-hidden />
          </span>
          <Link
            href={`/documents/${document.id}`}
            className="min-w-0 flex-1 rounded font-medium hover:underline"
          >
            <span className="block truncate" title={document.filename}>
              {document.filename}
            </span>
          </Link>
          <DropdownMenu>
            <DropdownMenuTrigger
              render={
                <Button
                  variant="ghost"
                  size="icon-sm"
                  aria-label={`Aksi untuk ${document.filename}`}
                  className="-mt-1 -mr-1"
                />
              }
            >
              <MoreHorizontal className="size-4" aria-hidden />
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              {/* Menu item di sini adalah tautan, bukan tombol: `nativeButton`
                  dimatikan supaya Base UI tidak memaksa elemen non-button. */}
              <DropdownMenuItem nativeButton={false} render={<Link href={`/documents/${document.id}`} />}>
                Lihat detail dan chunk
              </DropdownMenuItem>
              <DropdownMenuItem
                variant="destructive"
                onClick={() => setConfirmOpen(true)}
              >
                <Trash2 className="size-3.5" aria-hidden />
                Hapus dokumen
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>

        <p className="text-[12px] text-muted-foreground tnum">
          {document.page_count && document.page_count > 0
            ? `${document.page_count} halaman`
            : "Format teks"}{" "}
          <span aria-hidden>·</span> {formatBytes(document.size_bytes)}
          {document.chunk_count ? (
            <>
              {" "}
              <span aria-hidden>·</span> {document.chunk_count} chunk
            </>
          ) : null}
        </p>

        <div className="flex flex-wrap items-center gap-2">
          <DocumentStatusBadge status={document.status} />
          {failed && document.error_message ? (
            <span className="text-[12px] leading-snug text-muted-foreground">
              {document.error_message}
            </span>
          ) : null}
        </div>

        <div className="mt-auto flex items-center justify-between gap-2 border-t border-border pt-3">
          <span className="text-[12px] text-muted-foreground">
            Diunggah {formatRelative(document.uploaded_at)}
          </span>
          {document.status === "failed" ? (
            <>
              <Button
                variant="outline"
                size="sm"
                onClick={() => retryInputRef.current?.click()}
                className="h-7 gap-1.5"
              >
                <RotateCw className="size-3.5" aria-hidden />
                Unggah ulang
              </Button>
              <input
                ref={retryInputRef}
                type="file"
                accept=".pdf,.txt,.md,.markdown"
                className="sr-only"
                aria-label={`Pilih ulang berkas untuk ${document.filename}`}
                onChange={(event) => {
                  const file = event.target.files?.[0];
                  if (file) retryMutation.mutate(file);
                  event.target.value = "";
                }}
              />
            </>
          ) : (
            <Link
              // `?doc=` mengikat sesi baru ke dokumen ini, sehingga pencarian
              // hanya berjalan di dalamnya, bukan di seluruh korpus.
              href={`/chat?doc=${document.id}`}
              className="rounded text-[12px] font-medium text-brand-ink underline-offset-2 hover:underline"
            >
              Tanya dokumen ini
            </Link>
          )}
        </div>

        {busy ? (
          <p className="text-[12px] text-muted-foreground">
            {document.status === "processing"
              ? "Chunking dan embedding berjalan di server."
              : "Mengirim berkas ke server."}
          </p>
        ) : null}
      </div>

      <ConfirmDialog
        open={confirmOpen}
        onOpenChange={setConfirmOpen}
        title="Hapus dokumen ini?"
        description="Dokumen dan seluruh indeksnya akan dihapus permanen. Jawaban dan sitasi yang merujuk dokumen ini ikut kehilangan sumbernya."
        detail={`${document.filename} · ${document.chunk_count ?? 0} chunk`}
        confirmLabel="Hapus permanen"
        onConfirm={() => removeMutation.mutateAsync()}
      />
    </>
  );
}
