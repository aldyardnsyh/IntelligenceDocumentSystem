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
  /** Nama dokumen scope sesi, atau null untuk sesi lintas dokumen. */
  documentName: string | null;
  onRename: (session: ChatSession) => void;
  onDelete: (session: ChatSession) => void;
}

function SessionRow({ session, active, documentName, onRename, onDelete }: SessionRowProps) {
  return (
    <li className="group/session relative">
      {/*
        Baris sesi harus terbaca sebagai kartu percakapan, bukan sekadar teks
        di atas latar. Latarnya lebih gelap dari panel sidebar (`bg-muted`),
        dengan garis tepi halus supaya batas kartunya terlihat tanpa harus
        di-hover.

        Tombol titik-tiga selalu terlihat (opacity penuh), bukan hanya saat
        hover. Pada sidebar yang isinya banyak, tombol yang muncul-hilang
        membuat pengguna mengira aksinya tidak ada.
      */}
      <Link
        href={`/chat/${session.id}`}
        aria-current={active ? "page" : undefined}
        className={`flex flex-col gap-1 rounded-lg border py-2 pr-9 pl-3 transition-colors ${
          active
            ? "border-primary bg-primary text-primary-foreground shadow-sm"
            : "border-border/70 bg-muted/60 hover:border-brand/40 hover:bg-muted"
        }`}
      >
        <span className="truncate text-[13px] font-medium" title={session.title}>
          {session.title}
        </span>
        <span
          className={`flex items-center gap-1.5 truncate text-[11px] tnum ${
            active ? "text-primary-foreground/75" : "text-muted-foreground"
          }`}
        >
          {/*
            Scope ditandai di setiap baris: dengan chat per dokumen, dua sesi
            dengan judul mirip bisa mencari di ruang yang berbeda. Tanpa
            penanda ini, pengguna harus membuka satu per satu untuk tahu.
          */}
          {documentName ? (
            <>
              <FileText className="size-2.5 shrink-0" aria-hidden />
              <span className="truncate">{documentName}</span>
              <span aria-hidden>·</span>
            </>
          ) : (
            <>
              <span className="shrink-0">Semua dokumen</span>
              <span aria-hidden>·</span>
            </>
          )}
          <span className="shrink-0">{formatRelative(session.last_active_at)}</span>
        </span>
      </Link>

      <SessionActionsMenu
        session={session}
        onRename={onRename}
        onDelete={onDelete}
        placement="sidebar"
        className={
          active
            ? "opacity-100 text-primary-foreground hover:bg-primary-foreground/15 hover:text-primary-foreground aria-expanded:bg-primary-foreground/15 aria-expanded:text-primary-foreground"
            : "text-muted-foreground opacity-70 hover:bg-background hover:text-foreground hover:opacity-100 focus-visible:opacity-100 group-hover/session:opacity-100 group-focus-within/session:opacity-100"
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

  const documentNames = new Map((documents.data ?? []).map((item) => [item.id, item.filename]));
  // Urutan: sesi lintas dokumen dulu (paling sering dipakai), lalu per dokumen.
  const groupedSessions = (() => {
    const groups = new Map<string, { key: string; label: string; sessions: ChatSession[] }>();
    for (const session of sessions.data ?? []) {
      const scope = session.document_id ?? null;
      const key = scope ?? "__global__";
      const label = scope ? (documentNames.get(scope) ?? "Dokumen") : "Semua dokumen";
      const group = groups.get(key) ?? { key, label, sessions: [] };
      group.sessions.push(session);
      groups.set(key, group);
    }
    return [...groups.values()];
  })();

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
                    {/*
                      Jalan pintas ke chat privat dokumen ini. Tanpa tombol
                      ini, pengguna harus tahu bahwa scope dokumen itu ada,
                      fitur yang tidak punya pintu masuk sama saja tidak ada.
                    */}
                    <Link
                      href={`/chat?doc=${document.id}`}
                      className="ml-3 flex w-fit items-center gap-1.5 rounded px-2 py-1 text-[11px] font-medium text-brand-ink transition-colors hover:bg-brand-wash"
                    >
                      <MessageSquarePlus className="size-3" aria-hidden />
                      Tanya dokumen ini
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
              // Dikelompokkan per dokumen: dengan chat privat per dokumen,
              // "sesi ini mencari di mana" adalah informasi yang menentukan,
              // dan daftar datar menyembunyikannya.
              <div className="flex flex-col gap-4">
                {groupedSessions.map((group) => (
                  <div key={group.key} className="flex flex-col gap-1">
                    <p className="px-1 text-[11px] font-medium text-muted-foreground">
                      {group.label}
                    </p>
                    <ul className="flex flex-col gap-0.5">
                      {group.sessions.map((session) => (
                        <SessionRow
                          key={session.id}
                          session={session}
                          active={session.id === activeSessionId}
                          documentName={
                            session.document_id
                              ? (documentNames.get(session.document_id) ?? "Dokumen")
                              : null
                          }
                          onRename={onRenameSession}
                          onDelete={onDeleteSession}
                        />
                      ))}
                    </ul>
                  </div>
                ))}
              </div>
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
