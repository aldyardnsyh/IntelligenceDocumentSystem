"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, ChevronLeft, ChevronRight, FileText, MessageSquareText, Search, Trash2, TriangleAlert } from "lucide-react";
import { notify } from "@/lib/notify";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ConfirmDialog } from "@/components/common/confirm-dialog";
import { EmptyState } from "@/components/common/empty-state";
import { ErrorState } from "@/components/common/error-state";
import { LinkButton } from "@/components/common/link-button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { ChunkListSkeleton } from "@/components/common/skeletons";
import { ChunkList } from "@/components/documents/chunk-list";
import { DocumentPreview } from "@/components/documents/document-preview";
import { DocumentStatusBadge } from "@/components/documents/document-card";
import { deleteDocument, getDocument, getDocumentChunks } from "@/lib/api";
import { queryKeys } from "@/lib/queries";
import { ApiError } from "@/lib/api/error";
import { formatBytes, formatDateTime, formatNumber } from "@/lib/format";

const CHUNKS_PER_PAGE = 10;

export function DocumentDetailView() {
  const params = useParams<{ id: string }>();
  const searchParams = useSearchParams();
  const router = useRouter();
  const queryClient = useQueryClient();
  const searchRef = useRef<HTMLInputElement>(null);

  const documentId = params.id;
  const highlightRaw = searchParams.get("chunk");
  const parsedHighlight = highlightRaw === null ? null : Number.parseInt(highlightRaw, 10);
  const highlightChunkIndex =
    parsedHighlight !== null && !Number.isNaN(parsedHighlight) ? parsedHighlight : null;

  // Halaman awal dihitung dari `?chunk=`: sitasi menunjuk chunk yang bisa
  // berada di halaman lain. Nilainya dipakai sebagai nilai AWAL state, bukan
  // di-set lewat effect, `setState` di dalam effect memicu render berantai,
  // dan pada halaman ini effect debounce di bawah juga menulis `page`,
  // sehingga keduanya bisa saling memicu sampai halaman membeku.
  const highlightPage =
    highlightChunkIndex === null
      ? 1
      : Math.floor(highlightChunkIndex / CHUNKS_PER_PAGE) + 1;
  const [page, setPage] = useState(highlightPage);
  const [search, setSearch] = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");
  const [confirmOpen, setConfirmOpen] = useState(false);
  const seenHighlightRef = useRef(highlightChunkIndex);

  // Pencarian didebounce 300ms supaya tidak memanggil server tiap ketikan,
  // dan filter dijalankan di server, bukan di atas seluruh daftar chunk.
  // Kembali ke halaman 1 sekaligus dengan pencarian baru: hasil halaman 5
  // hampir pasti kosong setelah kata kunci berubah.
  useEffect(() => {
    const timer = setTimeout(() => {
      setDebouncedSearch(search);
      setPage(1);
    }, 300);
    return () => clearTimeout(timer);
  }, [search]);

  // Sitasi BARU saat komponen sudah ter-mount (URL berubah tanpa remount)
  // tetap harus mengosongkan pencarian dan melompat ke halaman chunk-nya.
  // Ditunda ke task berikutnya supaya tidak ada dua penulisan state berurutan
  // di dalam satu body effect.
  useEffect(() => {
    if (highlightChunkIndex === null) return;
    if (seenHighlightRef.current === highlightChunkIndex) return;
    seenHighlightRef.current = highlightChunkIndex;
    const timer = setTimeout(() => {
      setSearch("");
      setDebouncedSearch("");
      setPage(Math.floor(highlightChunkIndex / CHUNKS_PER_PAGE) + 1);
    }, 0);
    return () => clearTimeout(timer);
  }, [highlightChunkIndex]);

  const document = useQuery({
    queryKey: queryKeys.document(documentId),
    queryFn: ({ signal }) => getDocument(documentId, signal),
    enabled: Boolean(documentId),
    retry: false,
  });

  const chunks = useQuery({
    queryKey: queryKeys.documentChunks(documentId, page, debouncedSearch),
    queryFn: ({ signal }) =>
      getDocumentChunks(
        documentId,
        { page, pageSize: CHUNKS_PER_PAGE, search: debouncedSearch },
        signal,
      ),
    // Chunk belum ada selama ingestion berjalan, jadi tidak perlu memanggilnya.
    enabled: Boolean(documentId) && document.data?.status === "ready",
    retry: false,
    // Placeholder data halaman sebelumnya mencegah halaman berkedip kosong
    // saat pengguna mengganti halaman.
    placeholderData: (previous) => previous,
  });

  const removeMutation = useMutation({
    mutationFn: () => deleteDocument(documentId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.documents });
      notify.success(
        "Dokumen dihapus",
        "Seluruh chunk dan indeks vektornya ikut dibuang, jadi sitasi ke dokumen ini "
          + "tidak akan muncul lagi.",
      );
      router.push("/documents");
    },
    onError: (error) => {
      notify.error(error instanceof ApiError ? error.message : "Dokumen gagal dihapus.")
    },
  });

  if (document.isPending) {
    return (
      <div className="mx-auto flex w-full max-w-[1200px] flex-1 flex-col gap-6 px-4 py-8 sm:px-6">
        <div className="h-4 w-40 rounded bg-muted" aria-hidden />
        <div className="h-8 w-72 rounded bg-muted" aria-hidden />
        <div className="grid grid-cols-2 gap-4 lg:grid-cols-4" aria-hidden>
          {Array.from({ length: 4 }, (_, index) => (
            <div key={index} className="h-24 rounded-lg bg-card ring-1 ring-border" />
          ))}
        </div>
        <ChunkListSkeleton />
      </div>
    );
  }

  if (document.isError) {
    const notFound = document.error instanceof ApiError && document.error.isNotFound;
    return (
      <div className="mx-auto flex w-full max-w-[1200px] flex-1 flex-col gap-6 px-4 py-8 sm:px-6">
        {notFound ? (
          <EmptyState
            Icon={Search}
            title="Dokumen tidak ditemukan"
            description="Dokumen ini mungkin sudah dihapus, atau tautannya tidak lagi berlaku."
            action={
              <LinkButton variant="outline" className="mt-1 gap-1.5" href="/documents">
                <ArrowLeft className="size-4" aria-hidden />
                Kembali ke daftar dokumen
              </LinkButton>
            }
          />
        ) : (
          <ErrorState
            error={document.error}
            onRetry={() => document.refetch()}
            title="Detail dokumen gagal dimuat"
          />
        )}
      </div>
    );
  }

  const data = document.data;
  if (!data) return null;

  const isProcessing = data.status === "processing" || data.status === "uploading";
  const isFailed = data.status === "failed";

  const chunkData = chunks.data;
  const totalChunks = chunkData?.total ?? 0;
  const totalPages = Math.max(1, Math.ceil(totalChunks / CHUNKS_PER_PAGE));

  // Chunk yang disorot berasal dari sitasi di chat. Kalau hasil pencarian
  // yang aktif tidak memuatnya, sorotan dimatikan supaya tidak menunjuk ke
  // baris yang tidak ada.
  const highlightIsVisible =
    highlightChunkIndex !== null &&
    (chunkData?.items ?? []).some((chunk) => chunk.chunk_index === highlightChunkIndex);
  const activeHighlight = highlightIsVisible ? highlightChunkIndex : null;

  const metadata = [
    { label: "Ukuran berkas", value: formatBytes(data.size_bytes) },
    { label: "Tanggal unggah", value: formatDateTime(data.uploaded_at) },
    {
      label: "Jumlah chunk",
      value:
        data.chunk_count === null || data.chunk_count === undefined
          ? "Belum tersedia"
          : `${formatNumber(data.chunk_count)} chunk`,
    },
    { label: "Model embedding", value: data.ingestion.embedding_model },
  ];

  return (
    <div className="mx-auto flex w-full max-w-[1200px] flex-1 flex-col gap-6 px-4 py-8 sm:px-6">
      <div className="flex flex-col gap-4">
        <Link
          href="/documents"
          className="flex w-fit items-center gap-1.5 rounded text-[13px] text-muted-foreground hover:text-foreground"
        >
          <ArrowLeft className="size-3.5" aria-hidden />
          Kembali ke daftar dokumen
        </Link>

        <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
          <div className="flex min-w-0 flex-col gap-2">
            <h1 className="truncate text-2xl font-semibold tracking-tight">{data.filename}</h1>
            <div className="flex flex-wrap items-center gap-2">
              <DocumentStatusBadge status={data.status} />
              <Badge variant="outline" className="font-mono">
                {data.filename.split(".").pop()?.toUpperCase()}
              </Badge>
              {isProcessing ? (
                <span className="text-[12px] text-muted-foreground">
                  Chunk belum tersedia sampai ingestion selesai.
                </span>
              ) : null}
            </div>
            <p className="font-mono text-[11px] text-muted-foreground">{data.id}</p>
          </div>

          <div className="flex shrink-0 flex-wrap gap-2">
            <LinkButton variant="outline" className="gap-1.5" href="/chat">
              <MessageSquareText className="size-4" aria-hidden />
              Tanya di chat
            </LinkButton>
            <Button
              variant="destructive"
              className="gap-1.5"
              onClick={() => setConfirmOpen(true)}
            >
              <Trash2 className="size-4" aria-hidden />
              Hapus dokumen
            </Button>
          </div>
        </div>
      </div>

      {/*
        Empat kolom metadata memakai grid dengan label di atas nilai, supaya
        sekilas terbaca sebagai tabel data, bukan empat kartu seragam.
      */}
      <dl className="grid grid-cols-2 gap-px overflow-hidden rounded-lg bg-border ring-1 ring-border lg:grid-cols-4">
        {metadata.map((item) => (
          <div key={item.label} className="flex flex-col gap-1 bg-card px-4 py-3">
            <dt className="text-[11px] font-medium tracking-[0.06em] text-muted-foreground uppercase">
              {item.label}
            </dt>
            <dd className="truncate text-[14px] font-medium tnum" title={item.value}>
              {item.value}
            </dd>
          </div>
        ))}
      </dl>

      {/*
        Dua cara melihat dokumen yang sama, dan keduanya menjawab pertanyaan
        berbeda:

        - "Pratinjau isi": teks berurutan seperti di dokumen aslinya. Dipakai
          untuk cross-check apakah jawaban chat benar.
        - "Chunk hasil ingestion": bagaimana dokumen dipecah, beserta posisi
          karakter tiap potongan. Dipakai untuk memeriksa kualitas chunking.

        Sebelumnya hanya ada chunk. Daftar chunk tidak bisa dipakai menilai
        jawaban chat karena potongannya terpisah-pisah dan konteks di
        sekitarnya tidak terlihat.
      */}
      <Tabs defaultValue={highlightChunkIndex !== null ? "chunks" : "preview"}>
        <TabsList>
          <TabsTrigger value="preview">Pratinjau isi</TabsTrigger>
          <TabsTrigger value="chunks">Chunk hasil ingestion</TabsTrigger>
        </TabsList>

        <TabsContent value="preview" className="mt-4">
          {isProcessing || isFailed ? (
            <EmptyState
              Icon={FileText}
              title={
                isFailed
                  ? "Dokumen gagal diproses"
                  : "Isi dokumen belum tersedia"
              }
              description={
                isFailed
                  ? (data.error_message
                      ?? "Ingestion gagal, jadi tidak ada teks yang bisa ditampilkan.")
                  : "Teks tampil setelah ingestion selesai. Status di atas menunjukkan progresnya."
              }
            />
          ) : (
            <DocumentPreview documentId={data.id} filename={data.filename} />
          )}
        </TabsContent>

        <TabsContent value="chunks" className="mt-4">
      <section className="flex flex-col gap-3">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
          <div className="flex flex-col gap-1">
            <h2 className="text-lg font-semibold tracking-tight">Isi chunk hasil ingestion</h2>
            <p className="text-[13px] text-muted-foreground" aria-live="polite">
              {isProcessing || isFailed
                ? "Daftar chunk tampil setelah dokumen selesai diproses."
                : totalChunks === 0
                  ? "Belum ada chunk."
                  : debouncedSearch.trim().length > 0
                    ? `${formatNumber(totalChunks)} chunk mengandung "${debouncedSearch.trim()}".`
                    : `${formatNumber(totalChunks)} chunk dalam dokumen ini.`}
            </p>
          </div>
          <div className="relative sm:w-64">
            <Search
              className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-muted-foreground"
              aria-hidden
            />
            <Input
              ref={searchRef}
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Escape" && search.length > 0) {
                  event.preventDefault();
                  setSearch("");
                }
              }}
              placeholder="Cari kata kunci di dalam chunk"
              aria-label="Cari kata kunci di dalam chunk"
              className="pl-9"
            />
          </div>
        </div>

        {isProcessing ? (
          <EmptyState
            Icon={Search}
            title="Dokumen sedang diproses"
            description="Chunk baru tersedia setelah ekstraksi teks, pemecahan, dan embedding selesai. Halaman ini bisa dimuat ulang tanpa kehilangan dokumen."
          />
        ) : isFailed ? (
          <EmptyState
            Icon={TriangleAlert}
            title="Dokumen gagal diproses"
            description={
              data.error_message
                ?? "Dokumen ini tidak pernah selesai diproses, jadi tidak ada chunk yang bisa ditampilkan."
            }
          />
        ) : chunks.isError ? (
          <ErrorState
            error={chunks.error}
            onRetry={() => chunks.refetch()}
            title="Daftar chunk gagal dimuat"
          />
        ) : chunks.isPending ? (
          <ChunkListSkeleton count={CHUNKS_PER_PAGE} />
        ) : totalChunks === 0 ? (
          <EmptyState
            Icon={Search}
            title={
              debouncedSearch.trim().length > 0
                ? "Tidak ada chunk yang cocok"
                : "Dokumen ini tidak menghasilkan chunk"
            }
            description={
              debouncedSearch.trim().length > 0
                ? `Tidak ditemukan isi chunk yang mengandung "${debouncedSearch.trim()}".`
                : "Pemecahan tidak menghasilkan teks yang bisa diindeks. Periksa apakah berkas berisi teks, bukan hasil pindai."
            }
            action={
              debouncedSearch.trim().length > 0 ? (
                <Button variant="outline" size="sm" className="mt-1" onClick={() => setSearch("")}>
                  Hapus pencarian
                </Button>
              ) : undefined
            }
          />
        ) : (
          <>
            <ChunkList
              documentId={data.id}
              chunks={chunkData?.items ?? []}
              highlightChunkIndex={activeHighlight}
            />

            {totalPages > 1 ? (
              <div className="flex items-center justify-between gap-3 border-t border-border pt-3">
                <p className="text-[12px] text-muted-foreground tnum">
                  Menampilkan {(page - 1) * CHUNKS_PER_PAGE + 1} sampai{" "}
                  {Math.min(page * CHUNKS_PER_PAGE, totalChunks)} dari{" "}
                  {formatNumber(totalChunks)} chunk
                </p>
                <div className="flex items-center gap-1">
                  <Button
                    variant="outline"
                    size="icon-sm"
                    disabled={page <= 1 || chunks.isFetching}
                    onClick={() => setPage((value) => Math.max(1, value - 1))}
                    aria-label="Halaman chunk sebelumnya"
                  >
                    <ChevronLeft className="size-4" aria-hidden />
                  </Button>
                  <span className="px-2 text-[12px] tnum">
                    {page} / {totalPages}
                  </span>
                  <Button
                    variant="outline"
                    size="icon-sm"
                    disabled={page >= totalPages || chunks.isFetching}
                    onClick={() => setPage((value) => Math.min(totalPages, value + 1))}
                    aria-label="Halaman chunk berikutnya"
                  >
                    <ChevronRight className="size-4" aria-hidden />
                  </Button>
                </div>
              </div>
            ) : null}
          </>
        )}
      </section>
        </TabsContent>
      </Tabs>

      <ConfirmDialog
        open={confirmOpen}
        onOpenChange={setConfirmOpen}
        title="Hapus dokumen ini?"
        description="Dokumen dan seluruh indeksnya akan dihapus permanen dari vector store. Jawaban dan sitasi yang merujuk dokumen ini ikut kehilangan sumbernya."
        detail={`${data.filename} · ${formatNumber(data.chunk_count ?? 0)} chunk`}
        confirmLabel="Hapus permanen"
        onConfirm={() => removeMutation.mutateAsync()}
      />
    </div>
  );
}
