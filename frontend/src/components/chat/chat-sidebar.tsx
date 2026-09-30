"use client";

import Link from "next/link";
import { BarChart3, FileText, MessageSquarePlus, Settings } from "lucide-react";
import { Button } from "@/components/ui/button";
import { LinkButton } from "@/components/common/link-button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Separator } from "@/components/ui/separator";
import { DocumentStatusBadge } from "@/components/documents/document-card";
import { SessionListSkeleton } from "@/components/common/skeletons";
import { SessionActionsMenu } from "@/components/chat/session-actions-menu";
import { formatBytes, formatRelative } from "@/lib/format";
import { splitByReady, useDocuments, useSessions } from "@/lib/queries";
import type { ChatSession } from "@/types/api";

interface ChatSidebarProps {
  activeSessionId: string | null;
  onNewSession: () => void;
  onRenameSession: (session: ChatSession) => void;
  onDeleteSession: (session: ChatSession) => void;
  className?: string;
}

interface SessionRowProps {
  session: ChatSession;
  active: boolean;
  onRename: (session: ChatSession) => void;
  onDelete: (session: ChatSession) => void;
}

function SessionRow({ session, active, onRename, onDelete }: SessionRowProps) {
  return (
    <li className="group/session relative">
      <Link
        href={`/chat/${session.id}`}
        aria-current={active ? "page" : undefined}
        className={`flex flex-col gap-0.5 rounded-lg py-2 pr-9 pl-3 transition-colors ${
          active ? "bg-primary text-primary-foreground" : "hover:bg-muted"
        }`}
      >
        <span className="truncate text-[13px] font-medium" title={session.title}>
          {session.title}
        </span>
        <span
          className={`text-[11px] tnum ${active ? "text-primary-foreground/70" : "text-muted-foreground"}`}
        >
          {formatRelative(session.last_active_at)}
          {" · "}
          {session.message_count} pesan
        </span>
      </Link>

      {/*
        Tombol aksi disembunyikan sampai baris disorot atau difokus, supaya
        sidebar terbaca sebagai daftar percakapan, bukan daftar kendali.
        Baris yang aktif tetap menampilkannya, karena di sanalah pengguna
        berada dan aksi di situlah yang dicari.

        Untuk baris aktif, warna teks harus ditulis ulang di **semua** state
        interaktif. `variant="ghost"` membawa `hover:text-foreground` dan
        `aria-expanded:text-foreground`; keduanya pakai modifier berbeda dari
        `text-primary-foreground`, jadi tidak saling menggantikan dan tetap
        aktif. Akibatnya titik-titiknya putih saat diam lalu gelap saat di-hover
        di atas latar navy, jadi praktis tak terlihat. Menulis ulang keempat
        state itu lewat className sender mengalahkannya, karena className
        diproses belakangan oleh tailwind-merge.
      */}
      <SessionActionsMenu
        session={session}
        onRename={onRename}
        onDelete={onDelete}
        placement="sidebar"
        className={
          active
            ? "opacity-100 text-primary-foreground hover:bg-primary-foreground/15 hover:text-primary-foreground aria-expanded:bg-primary-foreground/15 aria-expanded:text-primary-foreground"
            : "opacity-0 transition-opacity focus-visible:opacity-100 group-hover/session:opacity-100 group-focus-within/session:opacity-100"
        }
      />
    </li>
  );
}

export function ChatSidebarContent({
  activeSessionId,
  onNewSession,
  onRenameSession,
  onDeleteSession,
}: ChatSidebarProps) {
  const documents = useDocuments();
  const sessions = useSessions();

  const { ready: readyDocuments, pending: pendingDocuments } = splitByReady(documents.data);

  return (
    <div className="flex h-full min-h-0 flex-col bg-card">
      <div className="p-3">
        <Button onClick={onNewSession} className="w-full justify-start gap-2">
          <MessageSquarePlus className="size-4" aria-hidden />
          Percakapan baru
        </Button>
      </div>

      <Separator />

      <ScrollArea className="min-h-0 flex-1">
        <div className="flex flex-col gap-5 p-3">
          <section className="flex flex-col gap-2">
            <h2 className="eyebrow px-1">Dokumen aktif</h2>
            {documents.isPending ? (
              <SessionListSkeleton rows={2} />
            ) : readyDocuments.length === 0 ? (
              <p className="px-1 text-[12px] leading-relaxed text-muted-foreground">
                Belum ada dokumen siap.{" "}
                <Link href="/documents" className="font-medium text-brand-ink underline underline-offset-2">
                  Unggah dokumen
                </Link>{" "}
                untuk mulai bertanya.
              </p>
            ) : (
              <ul className="flex flex-col gap-0.5">
                {readyDocuments.map((document) => (
                  <li key={document.id}>
                    <Link
                      href={`/documents/${document.id}`}
                      className="flex flex-col gap-1 rounded-lg px-3 py-2 transition-colors hover:bg-muted"
                    >
                      <span className="flex items-center gap-1.5">
                        <FileText className="size-3.5 shrink-0 text-muted-foreground" aria-hidden />
                        <span className="truncate text-[13px] font-medium">{document.filename}</span>
                      </span>
                      <span className="pl-5 text-[11px] text-muted-foreground tnum">
                        {formatBytes(document.size_bytes)}
                        {document.chunk_count ? ` · ${document.chunk_count} chunk` : null}
                      </span>
                    </Link>
                  </li>
                ))}
              </ul>
            )}

            {/* Status dokumen yang belum siap tetap terlihat supaya pengguna
                tahu kenapa chat terkunci, bukan hanya melihat input mati. */}
            {pendingDocuments.length > 0 ? (
              <ul className="flex flex-col gap-1.5 px-1 pt-1">
                {pendingDocuments.map((document) => (
                  <li key={document.id} className="flex items-center justify-between gap-2">
                    <span className="truncate text-[12px] text-muted-foreground">
                      {document.filename}
                    </span>
                    <DocumentStatusBadge status={document.status} />
                  </li>
                ))}
              </ul>
            ) : null}
          </section>

          <section className="flex flex-col gap-2">
            <h2 className="eyebrow px-1">Riwayat sesi</h2>
            {sessions.isPending ? (
              <SessionListSkeleton />
            ) : (sessions.data ?? []).length === 0 ? (
              <p className="px-1 text-[12px] leading-relaxed text-muted-foreground">
                Belum ada riwayat. Sesi tersimpan selama TTL memori aktif dan akan
                hilang setelah sesi berakhir.
              </p>
            ) : (
              <ul className="flex flex-col gap-0.5">
                {(sessions.data ?? []).map((session) => (
                  <SessionRow
                    key={session.id}
                    session={session}
                    active={session.id === activeSessionId}
                    onRename={onRenameSession}
                    onDelete={onDeleteSession}
                  />
                ))}
              </ul>
            )}
          </section>
        </div>
      </ScrollArea>

      <Separator />

      {/* /settings dan /analytics dijangkau dari mana pun, supaya tidak
          harus lewat navbar di setiap halaman. */}
      <nav aria-label="Navigasi lanjutan" className="flex gap-1 p-3">
        <LinkButton
          variant="ghost"
          size="sm"
          className="flex-1 justify-start gap-1.5 text-muted-foreground"
          href="/settings"
        >
          <Settings className="size-3.5" aria-hidden />
          Pengaturan
        </LinkButton>
        <LinkButton
          variant="ghost"
          size="sm"
          className="flex-1 justify-start gap-1.5 text-muted-foreground"
          href="/analytics"
        >
          <BarChart3 className="size-3.5" aria-hidden />
          Analitik
        </LinkButton>
      </nav>
    </div>
  );
}
