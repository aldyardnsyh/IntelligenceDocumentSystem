"use client";

import { useCallback, useState } from "react";
import { useRouter } from "next/navigation";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { notify } from "@/lib/notify";
import { deleteSession, renameSession } from "@/lib/api";
import { ApiError } from "@/lib/api/error";
import { queryKeys } from "@/lib/queries";
import type { ChatSession } from "@/types/api";

interface UseSessionActionsOptions {
  /** Sesi yang sedang dibuka, supaya hapus bisa memindah halaman bila perlu. */
  activeSessionId: string | null;
  /** Dipanggil setelah nama sesi aktif berubah, supaya judul header ikut. */
  onRenamed?: (sessionId: string, title: string) => void;
}

export interface SessionActions {
  /** Sesi yang sedang diubah namanya, atau null. */
  renaming: ChatSession | null;
  /** Sesi yang sedang dihapus, atau null. */
  deleting: ChatSession | null;
  startRename: (session: ChatSession) => void;
  startDelete: (session: ChatSession) => void;
  cancelRename: () => void;
  cancelDelete: () => void;
  confirmRename: (title: string) => Promise<void>;
  confirmDelete: () => Promise<void>;
  /** Judul terbaru dari daftar sesi, dengan fallback ke nilai yang diberikan. */
  liveTitleOf: (session: ChatSession | null) => string;
}

/**
 * Satu-satunya pemilik logika ubah nama dan hapus percakapan.
 *
 * Dipakai oleh sidebar dan header sekaligus, jadi keduanya tidak bisa
 * berbeda perilaku: satu dialog, satu mutation, satu pesan error, satu
 * keputusan navigasi. Kalau logika ini diduplikasi di dua tempat, cepat atau
 * lambat salah satunya akan tertinggal.
 */
export function useSessionActions({
  activeSessionId,
  onRenamed,
}: UseSessionActionsOptions): SessionActions {
  const router = useRouter();
  const queryClient = useQueryClient();
  const [renaming, setRenaming] = useState<ChatSession | null>(null);
  const [deleting, setDeleting] = useState<ChatSession | null>(null);

  const invalidateSessions = useCallback(() => {
    void queryClient.invalidateQueries({ queryKey: queryKeys.sessions });
  }, [queryClient]);

  const renameMutation = useMutation({
    mutationFn: ({ id, title }: { id: string; title: string }) => renameSession(id, title),
    onSuccess: (_result, variables) => {
      invalidateSessions();
      onRenamed?.(variables.id, variables.title);
      notify.success("Nama percakapan diperbarui");
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => deleteSession(id),
    onSuccess: (_result, id) => {
      invalidateSessions();
      notify.success(
        "Percakapan dihapus",
        "Sesi ini beserta pesanannya tidak bisa dibuka lagi.",
      );
      // Sesi yang sedang dibuka tidak boleh dibiarkan terbuka setelah dihapus:
      // history-nya sudah tidak ada, jadi halamannya akan jatuh ke error 404.
      if (id === activeSessionId) router.push("/chat");
    },
    onError: (error) => {
      notify.error(error instanceof ApiError ? error.message : "Percakapan gagal dihapus.",)
      // Sesi mungkin sudah hilang di server. Segarkan daftar supaya barisnya
      // ikut hilang, kalau tidak user akan melihat tombol yang selalu gagal.
      invalidateSessions();
    },
  });

  const liveTitleOf = useCallback(
    (session: ChatSession | null) => {
      if (!session) return "";
      const fresh = queryClient
        .getQueryData<ChatSession[]>(queryKeys.sessions)
        ?.find((item) => item.id === session.id);
      return fresh?.title ?? session.title;
    },
    [queryClient],
  );

  return {
    renaming,
    deleting,
    startRename: setRenaming,
    startDelete: setDeleting,
    cancelRename: () => setRenaming(null),
    cancelDelete: () => setDeleting(null),
    confirmRename: async (title: string) => {
      if (!renaming) return;
      try {
        await renameMutation.mutateAsync({ id: renaming.id, title });
      } catch (error) {
        // dilempar supaya RenameSessionDialog bisa menampilkannya inline dan
        // membiarkan isinya tetap ada, bukan cuma lewat toast yang lewat begitu
        throw error instanceof ApiError
          ? error
          : new ApiError("Gagal menyimpan nama percakapan.", 500);
      }
    },
    confirmDelete: async () => {
      if (!deleting) return;
      await deleteMutation.mutateAsync(deleting.id);
    },
    liveTitleOf,
  };
}
