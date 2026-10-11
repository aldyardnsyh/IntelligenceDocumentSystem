"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { FileText, Upload } from "lucide-react";
import { notify } from "@/lib/notify";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { ErrorState } from "@/components/common/error-state";
import { CitationSkeleton, MessageSkeleton } from "@/components/common/skeletons";
import { ConfirmDialog } from "@/components/common/confirm-dialog";
import { ChatEmptyState } from "./chat-empty-state";
import { ChatInput } from "./chat-input";
import { ChatSidebarContent } from "./chat-sidebar";
import { MessageBubble } from "./message-bubble";
import { RenameSessionDialog } from "./rename-session-dialog";
import { SessionTitleBar, SidebarToggle } from "./session-title-bar";
import { useChat } from "./use-chat";
import { useSessionActions } from "./use-session-actions";
import { uploadDocument } from "@/lib/api";
import { ApiError } from "@/lib/api/error";
import { queryKeys, useDocuments, useSessions } from "@/lib/queries";
import { SESSION_TITLE_MAX_LENGTH } from "@/lib/mock/store";
import type { ChatSession } from "@/types/api";

interface ChatShellProps {
  /** null untuk /chat (sesi baru), id untuk /chat/[sessionId]. */
  sessionId?: string | null;
  /** Scope dokumen dari `?doc=`, untuk memulai chat privat dokumen itu. */
  documentId?: string | null;
}

export function ChatShell({
  sessionId: routeSessionId = null,
  documentId: routeDocumentId = null,
}: ChatShellProps) {
  const router = useRouter();
  const queryClient = useQueryClient();
  // Default menyala: pengguna memilih mode ini secara sadar, dan tanpa itu
  // pertanyaan di luar dokumen hanya dijawab "tidak ditemukan". Jawabannya
  // tetap dilabeli sebagai bukan dari dokumen.
  const [allowUngrounded, setAllowUngrounded] = useState(true);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [attachmentPending, setAttachmentPending] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const promotedToRoute = useRef<string | null>(routeSessionId);

  const documents = useDocuments();
  const sessions = useSessions();

  const activeSession: ChatSession | null =
    sessions.data?.find((item) => item.id === routeSessionId) ?? null;

  // Scope dokumen untuk sesi BARU datang dari `?doc=` di URL. Untuk sesi yang
  // sudah ada, `useChat` sendiri yang tahu scope-nya (dari riwayat sesi yang
  // dimuat), dan itu lebih andal daripada menunggu daftar sesi termuat.
  //
  // Versi sebelumnya mengambil scope HANYA dari `sessions.data`. Kalau daftar
  // itu sedang refetch, `activeSession` menjadi null, scope ikut null, dan
  // pertanyaan lanjutan mencari di SELURUH dokumen, kebocoran yang tidak
  // terlihat di UI.
  const initialDocumentId = routeSessionId ? null : routeDocumentId;

  const chat = useChat(routeSessionId ?? undefined, "", {
    documentId: initialDocumentId,
    allowUngrounded,
  });

  // Scope yang sedang aktif, dari sumber paling tepercaya ke paling lemah.
  const activeDocumentId =
    chat.sessionDocumentId ?? activeSession?.document_id ?? routeDocumentId ?? null;
  const scopedDocument = activeDocumentId
    ? ((documents.data ?? []).find((item) => item.id === activeDocumentId) ?? null)
    : null;

  const activeSessionId = routeSessionId ?? chat.sessionId;

  /*
   * ChatShell adalah satu-satunya pemilik aksi ubah nama dan hapus. Sidebar
   * dan header sama-sama memanggil hook ini, jadi tidak ada dua salinan
   * logika yang bisa bertingkah berbeda.
   */
  const actions = useSessionActions({
    activeSessionId,
    onRenamed: (id, title) => {
      if (id === activeSessionId) chat.setTitle(title);
    },
  });

  const readyDocuments = (documents.data ?? []).filter((item) => item.status === "ready");

  const uploadMutation = useMutation({
    mutationFn: (file: File) => uploadDocument(file),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.documents });
      notify.success(
        "Dokumen diterima",
        "Tunggu sampai statusnya Siap ditanyai sebelum bisa dipakai bertanya.",
      );
    },
    onError: (error) => {
      notify.error(error instanceof ApiError ? error.message : "Gagal melampirkan dokumen.",)
    },
    onSettled: () => setAttachmentPending(false),
  });

  // Setelah stream selesai, alamat ikut naik ke /chat/[sessionId] supaya
  // percakapan bisa dibagikan dan dibuka ulang lewat sidebar.
  //
  // PENTING: navigasi harus menunggu stream selesai. `/chat` dan
  // `/chat/[sessionId]` adalah dua halaman berbeda, jadi `router.replace`
  // saat jawaban masih mengalir akan melepas ChatShell lama, cleanup hook
  // membatalkan fetch, dan jawaban pertama tidak pernah sampai ke layar.
  useEffect(() => {
    const id = chat.sessionId;
    if (!id || routeSessionId) return;
    if (chat.isSending) return;
    if (promotedToRoute.current === id) return;
    promotedToRoute.current = id;
    router.replace(`/chat/${id}`);
  }, [chat.sessionId, chat.isSending, routeSessionId, router]);

  // Auto-scroll mengikuti pesan baru dan token streaming.
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ block: "end" });
  }, [chat.messages]);

  const lastMessage = chat.messages[chat.messages.length - 1];
  // Dokumen ber-scope dianggap cukup untuk bertanya meski daftar global belum
  // termuat: pengguna sudah memilih dokumennya, dan memblokir di sini hanya
  // membuat tombol kirim mati tanpa alasan yang terlihat.
  const canAsk = readyDocuments.length > 0 || scopedDocument?.status === "ready";
  const disabledReason = canAsk
    ? null
    : documents.isPending
      ? "Memeriksa daftar dokumen..."
      : "Belum ada dokumen siap. Unggah dokumen terlebih dahulu.";

  const handleSend = (question: string) => {
    if (!canAsk) {
      notify.warning(
        "Belum ada dokumen siap",
        "Unggah dokumen lebih dulu di halaman Dokumen, lalu tunggu sampai selesai diproses.",
      );
      return;
    }
    chat.send(question);
  };

  const sidebar = (
    <ChatSidebarContent
      activeSessionId={activeSessionId}
      onNewSession={() => {
        chat.startNewSession();
        promotedToRoute.current = null;
        setSidebarOpen(false);
        router.push("/chat");
      }}
      onRenameSession={(session) => {
        setSidebarOpen(false);
        actions.startRename(session);
      }}
      onDeleteSession={(session) => {
        setSidebarOpen(false);
        actions.startDelete(session);
      }}
    />
  );

  return (
    <div className="flex min-h-0 flex-1">
      {/* Sidebar permanen di desktop, drawer di layar kecil. */}
      <aside className="hidden w-70 shrink-0 border-r border-border lg:block">{sidebar}</aside>

      <div className="flex min-w-0 flex-1 flex-col">
        {/*
          Bar ini muncul di semua lebar layar. Judul sesi beserta menu aksinya
          adalah tempat yang sedang dibaca pengguna, jadi harus ada di sana.
          Tombol sidebar pindah ke baris yang sama di mobile supaya tidak
          memakan ruang vertikal.
        */}
        <div className="flex items-center gap-2 border-b border-border px-3 py-2">
          <SidebarToggle onClick={() => setSidebarOpen(true)} className="lg:hidden" />
          <SessionTitleBar
            session={activeSession}
            title={actions.liveTitleOf(activeSession) || chat.sessionTitle}
            onRename={actions.startRename}
            onDelete={actions.startDelete}
          />
          {/*
            Badge scope: dengan chat privat per dokumen, "percakapan ini
            mencari di mana" adalah informasi yang menentukan jawaban. Tanpa
            badge, pengguna tidak bisa membedakan sesi global dari sesi dokumen.
          */}
          {/*
            Badge scope: dengan chat privat per dokumen, "percakapan ini
            mencari di mana" adalah informasi yang menentukan jawaban.

            Dua mode ini harus terlihat BEDA, bukan sekadar berbeda teks:
            - Sesi dokumen: badge berlatar brand (menonjol) dengan nama berkas.
            - Sesi global: badge abu-abu bertuliskan "Semua dokumen".

            Sebelumnya keduanya nyaris sama, jadi pengguna tidak bisa tahu
            mode mana yang sedang aktif, dan itu yang membuat scope terasa
            tidak sinkron.
          */}
          {activeDocumentId ? (
            <span
              className="ml-auto flex min-w-0 shrink items-center gap-1.5 rounded-full bg-brand px-2.5 py-1 text-[11px] font-semibold text-primary-foreground"
              title={`Pencarian dibatasi ke ${scopedDocument?.filename ?? "satu dokumen"}`}
            >
              <FileText className="size-3 shrink-0" aria-hidden />
              <span className="truncate">
                {scopedDocument ? scopedDocument.filename : "Satu dokumen"}
              </span>
            </span>
          ) : (
            <span
              className="ml-auto shrink-0 rounded-full border border-dashed border-border px-2.5 py-1 text-[11px] font-medium text-muted-foreground"
              title="Pencarian mencakup semua dokumen yang siap"
            >
              Semua dokumen
            </span>
          )}
        </div>

        <div className="flex-1 overflow-y-auto scrollbar-slim">
          <div className="mx-auto flex w-full max-w-[768px] flex-col gap-6 px-4 py-6">
            {chat.isLoadingHistory ? (
              <MessageSkeleton />
            ) : chat.historyError ? (
              <ErrorState
                error={chat.historyError}
                onRetry={() => router.push("/chat")}
                title="Riwayat sesi gagal dimuat"
              />
            ) : chat.messages.length === 0 ? (
              <ChatEmptyState
                documents={readyDocuments}
                onPick={handleSend}
                onUpload={() => fileInputRef.current?.click()}
              />
            ) : (
              chat.messages.map((message) => (
                <MessageBubble
                  key={message.id}
                  message={message}
                  onRetry={message.state === "error" ? chat.retry : undefined}
                />
              ))
            )}

            {/*
              Placeholder sitasi muncul selama jawaban masih mengalir: user
              tahu jawaban akan membawa sumber sebelum sumbernya terlihat.
            */}
            {lastMessage?.role === "assistant" && lastMessage.state === "streaming" ? (
              <div className="flex justify-start">
                <CitationSkeleton />
              </div>
            ) : null}

            <div ref={bottomRef} />
          </div>
        </div>

        <div className="sticky bottom-0 border-t border-border bg-background/95 px-4 py-3 backdrop-blur-sm">
          <div className="mx-auto w-full max-w-[768px]">
            {chat.rateLimit ? (
              <p
                role="status"
                className="mb-2 flex items-center gap-2 rounded-md border border-warning/40 bg-warning/5 px-3 py-2 text-[13px] text-warning-ink"
              >
                {chat.rateLimit.message} Coba lagi dalam {chat.rateLimit.seconds} detik.
              </p>
            ) : null}

            <ChatInput
              onSend={handleSend}
              onStop={chat.stop}
              isSending={chat.isSending}
              disabledReason={disabledReason}
              allowUngrounded={allowUngrounded}
              onAllowUngroundedChange={setAllowUngrounded}
              onAttach={(file) => {
                setAttachmentPending(true);
                uploadMutation.mutate(file);
              }}
            />

            <input
              ref={fileInputRef}
              type="file"
              accept=".pdf,.txt,.md,.markdown"
              className="sr-only"
              aria-label="Unggah dokumen"
              onChange={(event) => {
                const file = event.target.files?.[0];
                if (file) uploadMutation.mutate(file);
                event.target.value = "";
              }}
            />

            {attachmentPending || uploadMutation.isPending ? (
              <p className="mt-2 flex items-center gap-1.5 text-[12px] text-muted-foreground">
                <Upload className="size-3" aria-hidden />
                Mengunggah dokumen...
              </p>
            ) : null}
          </div>
        </div>
      </div>

      <Sheet open={sidebarOpen} onOpenChange={setSidebarOpen}>
        <SheetContent side="left" showCloseButton={false} className="w-72 p-0 sm:max-w-72">
          <SheetHeader className="sr-only">
            <SheetTitle>Dokumen dan riwayat sesi</SheetTitle>
            <SheetDescription>
              Daftar dokumen aktif dan riwayat percakapan pada sesi ini.
            </SheetDescription>
          </SheetHeader>
          {sidebar}
        </SheetContent>
      </Sheet>

      {/*
        Key di bawah sengaja berubah saat target berpindah: itu yang membuat
        dialog remount dan isinya kembali kosong, jadi judul lama tidak
        tertinggal di input. Versi sebelumnya memakai `?? "none"` untuk
        keduanya, sehingga saat dua dialog sama-sama tertutup keduanya mendapat
        key `"none"` dan React memperingatkan key duplikat. Diawali dengan
        prefiks berbeda supaya tetap unik tanpa mengubah perilaku remount.
      */}
      <RenameSessionDialog
        key={`rename:${actions.renaming?.id ?? "closed"}`}
        open={actions.renaming !== null}
        onOpenChange={(open) => {
          if (!open) actions.cancelRename();
        }}
        currentTitle={actions.liveTitleOf(actions.renaming)}
        maxLength={SESSION_TITLE_MAX_LENGTH}
        onSubmit={actions.confirmRename}
      />

      <ConfirmDialog
        key={`delete:${actions.deleting?.id ?? "closed"}`}
        open={actions.deleting !== null}
        onOpenChange={(open) => {
          if (!open) actions.cancelDelete();
        }}
        title="Hapus percakapan ini?"
        description="Seluruh pesan dan sumber yang dikutip di dalamnya akan dihapus permanen. Tindakan ini tidak dapat dibatalkan."
        detail={
          actions.deleting
            ? `${actions.liveTitleOf(actions.deleting)} · ${actions.deleting.message_count} pesan`
            : undefined
        }
        confirmLabel="Hapus percakapan"
        onConfirm={actions.confirmDelete}
      />
    </div>
  );
}
