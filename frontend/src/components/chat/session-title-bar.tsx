"use client";

import { Menu } from "lucide-react";
import { Button } from "@/components/ui/button";
import { SessionActionsMenu } from "@/components/chat/session-actions-menu";
import type { ChatSession } from "@/types/api";

interface SessionTitleBarProps {
  /** null saat belum ada sesi, judulnya jadi teks mati tanpa tombol. */
  session: ChatSession | null;
  title: string;
  onRename: (session: ChatSession) => void;
  onDelete: (session: ChatSession) => void;
}

/**
 * Bar judul sesi. Tidak menyimpan logika apa pun: aksi diteruskan ke atas,
 * dan menu memakai komponen yang sama dengan sidebar.
 */
export function SessionTitleBar({ session, title, onRename, onDelete }: SessionTitleBarProps) {
  if (!session) {
    return (
      <p className="min-w-0 flex-1 truncate text-[15px] font-semibold text-muted-foreground">
        Percakapan baru
      </p>
    );
  }

  return (
    <div className="flex min-w-0 flex-1 items-center gap-1.5">
      <h1 className="min-w-0 truncate text-[15px] font-semibold" title={title}>
        {title}
      </h1>
      <SessionActionsMenu
        session={session}
        onRename={onRename}
        onDelete={onDelete}
        placement="header"
      />
    </div>
  );
}

interface SidebarToggleProps {
  onClick: () => void;
  className?: string;
}

/** Tombol pembuka drawer di layar kecil. */
export function SidebarToggle({ onClick, className }: SidebarToggleProps) {
  return (
    <Button
      variant="outline"
      size="sm"
      onClick={onClick}
      className={`gap-1.5 ${className ?? ""}`}
    >
      <Menu className="size-4" aria-hidden />
      <span className="sr-only sm:not-sr-only">Dokumen dan riwayat</span>
    </Button>
  );
}
