"use client";

import { useEffect } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { TooltipProvider } from "@/components/ui/tooltip";
import { ApiError } from "@/lib/api/error";
import { resetStaleBrowserState } from "@/lib/boot-reset";

/**
 * Query client dibuat per render agar tidak dibagikan antar request server.
 * retry hanya untuk error transien: 5xx dan putus koneksi. 404 atau 422 tidak
 * akan membaik dengan dicoba ulang.
 */
function makeQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 15_000,
        refetchOnWindowFocus: false,
        retry: (failureCount, error) => {
          if (error instanceof ApiError && !error.isTransient) return false;
          return failureCount < 2;
        },
      },
      mutations: {
        retry: false,
      },
    },
  });
}

let browserQueryClient: QueryClient | undefined;

function getQueryClient() {
  if (typeof window === "undefined") return makeQueryClient();
  browserQueryClient ??= makeQueryClient();
  return browserQueryClient;
}

export function Providers({ children }: { children: React.ReactNode }) {
  const queryClient = getQueryClient();

  // Satu kali per pemuatan halaman: kalau backend ternyata baru dijalankan
  // ulang, sesi browser yang tersisa dibuang dan pengguna diminta masuk
  // ulang. Sesi memori tidak bertahan melewati restart, jadi mempertahankan
  // penanda login hanya membuat pengguna menemukan riwayat yang kosong.
  useEffect(() => {
    void resetStaleBrowserState();
  }, []);

  return (
    <QueryClientProvider client={queryClient}>
      <TooltipProvider delay={200}>{children}</TooltipProvider>
    </QueryClientProvider>
  );
}
