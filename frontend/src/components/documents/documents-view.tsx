"use client";

import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FolderOpen, Loader2, Search } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { EmptyState } from "@/components/common/empty-state";
import { ErrorState } from "@/components/common/error-state";
import { DocumentGridSkeleton } from "@/components/common/skeletons";
import { DocumentCard } from "@/components/documents/document-card";
import { UploadDropzone } from "@/components/documents/upload-dropzone";
import { listDocuments, uploadDocument } from "@/lib/api";
import { queryKeys } from "@/lib/queries";
import { ApiError } from "@/lib/api/error";
import type { DocumentStatus } from "@/types/api";

const FILTERS = [
  { key: "all", label: "Semua" },
  { key: "ready", label: "Siap" },
  { key: "processing", label: "Diproses" },
  { key: "failed", label: "Gagal" },
] as const;

type FilterKey = (typeof FILTERS)[number]["key"];

const MATCHES: Record<FilterKey, DocumentStatus[]> = {
  all: ["ready", "processing", "uploading", "failed"],
  ready: ["ready"],
  processing: ["processing", "uploading"],
  failed: ["failed"],
};

export function DocumentsView() {
  const queryClient = useQueryClient();
  const [filter, setFilter] = useState<FilterKey>("all");
  const [search, setSearch] = useState("");

  const documents = useQuery({
    queryKey: queryKeys.documents,
    queryFn: ({ signal }) => listDocuments(signal),
    // Status ingestion berubah di server, jadi poll hanya selama ada dokumen
    // yang masih diproses. Setelah semuanya selesai, polling berhenti.
    refetchInterval: (query) => {
      const items = query.state.data ?? [];
      const pending = items.some(
        (item) => item.status === "processing" || item.status === "uploading",
      );
      return pending ? 1500 : false;
    },
  });

  const uploadMutation = useMutation({
    mutationFn: (file: File) => uploadDocument(file),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.documents });
      toast.success("Berkas diterima. Pemrosesan dokumen berjalan di server.");
    },
    onError: (error) => {
      toast.error(
        error instanceof ApiError ? error.message : "Gagal mengunggah berkas. Periksa format berkas.",
      );
    },
  });

  const counts = useMemo(() => {
    const items = documents.data ?? [];
    return {
      all: items.length,
      ready: items.filter((item) => item.status === "ready").length,
      processing: items.filter(
        (item) => item.status === "processing" || item.status === "uploading",
      ).length,
      failed: items.filter((item) => item.status === "failed").length,
    } satisfies Record<FilterKey, number>;
  }, [documents.data]);

  const visible = useMemo(() => {
    const items = documents.data ?? [];
    const term = search.trim().toLowerCase();
    return items.filter(
      (item) =>
        MATCHES[filter].includes(item.status) &&
        (term.length === 0 || item.filename.toLowerCase().includes(term)),
    );
  }, [documents.data, filter, search]);

  const isInitialLoad = documents.isPending;
  const isEmptyCorpus = !documents.isPending && (documents.data?.length ?? 0) === 0;

  return (
    <div className="mx-auto flex w-full max-w-[1200px] flex-1 flex-col gap-6 px-4 py-8 sm:px-6">
      <header className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div className="flex flex-col gap-1.5">
          <p className="eyebrow">Penyimpanan dan vektorisasi</p>
          <h1 className="text-2xl font-semibold tracking-tight">Dokumen Saya</h1>
          <p className="max-w-2xl text-[13px] leading-relaxed text-muted-foreground">
            Dokumen yang berstatus siap akan otomatis dipakai sebagai sumber
            retrieval saat Anda bertanya. Dokumen yang masih diproses belum bisa
            ditanyai.
          </p>
        </div>
        <UploadDropzone
          compact
          busy={uploadMutation.isPending}
          onSelect={(file) => uploadMutation.mutate(file)}
          className="shrink-0"
        />
      </header>

      {isEmptyCorpus ? (
        <EmptyState
          Icon={FolderOpen}
          title="Belum ada dokumen"
          description="Unggah satu dokumen PDF, TXT, atau Markdown sebagai sumber pertama. Tanpa dokumen, chat tidak bisa menjawab apa pun."
        />
      ) : (
        <>
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <div role="tablist" aria-label="Saring dokumen" className="flex flex-wrap gap-1">
              {FILTERS.map(({ key, label }) => {
                const active = filter === key;
                return (
                  <button
                    key={key}
                    role="tab"
                    type="button"
                    aria-selected={active}
                    onClick={() => setFilter(key)}
                    className={`rounded-md px-3 py-1.5 text-[13px] font-medium transition-colors ${
                      active
                        ? "bg-primary text-primary-foreground"
                        : "bg-muted text-muted-foreground hover:text-foreground"
                    }`}
                  >
                    {label}
                    <span className="ml-1.5 tnum opacity-70">{counts[key]}</span>
                  </button>
                );
              })}
            </div>

            <div className="relative sm:w-64">
              <Search
                className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted-foreground"
                aria-hidden
              />
              <Input
                value={search}
                onChange={(event) => setSearch(event.target.value)}
                placeholder="Cari nama dokumen"
                aria-label="Cari nama dokumen"
                className="pl-9"
              />
            </div>
          </div>

          {documents.isError ? (
            <ErrorState
              error={documents.error}
              onRetry={() => documents.refetch()}
              title="Daftar dokumen gagal dimuat"
            />
          ) : null}

          {isInitialLoad ? (
            <DocumentGridSkeleton />
          ) : visible.length === 0 ? (
            <EmptyState
              Icon={FolderOpen}
              title="Tidak ada dokumen yang cocok"
              description={
                search.trim().length > 0
                  ? `Tidak ada berkas bernama mengandung "${search.trim()}".`
                  : "Tidak ada dokumen pada status ini. Ganti saringan atau unggah berkas baru."
              }
              action={
                <Button
                  variant="outline"
                  size="sm"
                  className="mt-1"
                  onClick={() => {
                    setSearch("");
                    setFilter("all");
                  }}
                >
                  Tampilkan semua dokumen
                </Button>
              }
            />
          ) : (
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-3">
              {visible.map((document) => (
                <DocumentCard key={document.id} document={document} />
              ))}
            </div>
          )}

          {uploadMutation.isPending ? (
            <p className="flex items-center gap-2 text-[13px] text-muted-foreground">
              <Loader2 className="size-3.5 animate-spin" aria-hidden />
              Mengirim berkas ke server...
            </p>
          ) : null}
        </>
      )}

      {/*
        Drop zone besar hanya tampil saat korpus masih kosong. Setelah ada
        dokumen, aksi unggah pindah ke tombol header supaya tidak memakan
        ruang grid (design.md 5).
      */}
      {isEmptyCorpus ? (
        <UploadDropzone onSelect={(file) => uploadMutation.mutate(file)} />
      ) : null}
    </div>
  );
}
