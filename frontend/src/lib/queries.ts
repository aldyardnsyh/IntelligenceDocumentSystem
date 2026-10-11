import { useQuery } from "@tanstack/react-query";
import { listDocuments, listSessions } from "@/lib/api";

/**
 * Kunci cache ditulis di satu tempat supaya tidak ada salah ketik.
 * `["sessions"]` yang ditulis literal di beberapa komponen sangat mudah
 * berbeda satu karakter tanpa ketahuan, dan akibatnya cache tidak pernah
 * invalidasi.
 */
export const queryKeys = {
  sessions: ["sessions"] as const,
  documents: ["documents"] as const,
  document: (id: string) => ["documents", id] as const,
  documentPreview: (id: string) => ["documents", id, "preview"] as const,
  documentChunks: (id: string, page: number, search: string) =>
    ["documents", id, "chunks", page, search] as const,
  settings: ["settings"] as const,
  analyticsSummary: ["analytics", "summary"] as const,
  analyticsLogs: (page: number) => ["analytics", "logs", page] as const,
};

/** Satu-satunya tempat `GET /chat/sessions` dipanggil. */
export function useSessions() {
  return useQuery({
    queryKey: queryKeys.sessions,
    queryFn: ({ signal }) => listSessions(signal),
  });
}

/**
 * Dokumen aktif dipolling karena status ingestion berubah di server.
 * Polling hanya berjalan selama ada dokumen yang masih diproses, lalu berhenti
 * supaya tidak mengirim permintaan sia-sia.
 */
export function useDocuments() {
  return useQuery({
    queryKey: queryKeys.documents,
    queryFn: ({ signal }) => listDocuments(signal),
    refetchInterval: (query) => {
      const items = query.state.data ?? [];
      const pending = items.some(
        (item) => item.status === "processing" || item.status === "uploading",
      );
      return pending ? 1500 : false;
    },
  });
}

/** Membagi daftar dokumen berstatus siap dan belum siap. */
export function splitByReady<T extends { status: string }>(items: T[] | undefined) {
  const list = items ?? [];
  return {
    ready: list.filter((item) => item.status === "ready"),
    pending: list.filter((item) => item.status !== "ready"),
  };
}
