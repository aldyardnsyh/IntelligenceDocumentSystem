"use client";

import { MoreHorizontal, Pencil, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import type { ChatSession } from "@/types/api";

interface SessionActionsMenuProps {
  session: ChatSession;
  onRename: (session: ChatSession) => void;
  onDelete: (session: ChatSession) => void;
  /**
   * `sidebar` menaruh tombol melayang di atas baris percakapan; `header`
   * menampilkannya di sebelah judul.
   *
   *Keempat kelas warna dan visibilitas sepenuhnya diserahkan ke pemanggil
   * lewat `className`, karena keputusannya berbeda per konteks: di header
   * tombolnya berlatar terang, sedangkan di sidebar bisa berada di atas baris
   * biru yang aktif. Memaksakan gaya di sini pernah membuat tombol gelap di
   * atas latar navy. Menu hanya mengurus penempatan.
   */
  placement: "sidebar" | "header";
  className?: string;
}

/**
 * Menu aksi percakapan, dipakai sidebar dan header tanpa perbedaan isi.
 *
 * Satu komponen untuk dua tempat penting supaya dua aksi ini tidak pernah
 * berbeda:item yang sama, urutan yang sama, dan label yang sama. Kalau menu
 * di header punya satu item yang tidak ada di sidebar, user akan mencari
 * aksinya di tempat yang salah.
 */
export function SessionActionsMenu({
  session,
  onRename,
  onDelete,
  placement,
  className,
}: SessionActionsMenuProps) {
  const onSidebar = placement === "sidebar";

  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        render={
          <Button
            variant="ghost"
            size={onSidebar ? "icon-xs" : "icon-sm"}
            aria-label={`Aksi untuk percakapan ${session.title}`}
            title="Aksi percakapan"
            className={onSidebar ? `absolute top-1.5 right-1.5 ${className ?? ""}` : className}
          />
        }
      >
        <MoreHorizontal className={onSidebar ? "size-4" : "size-3.5"} aria-hidden />
      </DropdownMenuTrigger>

      <DropdownMenuContent align="end">
        <DropdownMenuItem onClick={() => onRename(session)}>
          <Pencil className="size-3.5" aria-hidden />
          Ubah nama
        </DropdownMenuItem>
        <DropdownMenuItem variant="destructive" onClick={() => onDelete(session)}>
          <Trash2 className="size-3.5" aria-hidden />
          Hapus percakapan
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
