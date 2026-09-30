"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import {
  askQuestion,
  getHistory,
  newSessionId,
} from "@/lib/api";
import { queryKeys } from "@/lib/queries";
import { ApiError, toApiError } from "@/lib/api/error";
import type { Citation } from "@/types/api";

export type MessageState = "thinking" | "streaming" | "done" | "error";

export interface UiMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  citations: Citation[];
  notFound: boolean;
  state: MessageState;
  errorMessage?: string;
}

export interface ChatController {
  messages: UiMessage[];
  sessionId: string | null;
  /** Judul sesi, setelah diubah manual kalau sempat diubah. */
  sessionTitle: string;
  isLoadingHistory: boolean;
  isSending: boolean;
  historyError: unknown;
  rateLimit: { message: string; seconds: number } | null;
  send: (question: string) => void;
  stop: () => void;
  retry: () => void;
  startNewSession: () => void;
  setTitle: (title: string) => void;
  refreshHistory: () => void;
}

/**
 * Seluruh state percakapan hidup di satu hook supaya tidak ada dua sumber
 * kebenaran antara input, streaming, dan sidebar.
 *
 * `startNewSession` sengaja tidak menghapus riwayat di server: pengguna masih
 * bisa membuka kembali sesi lama lewat sidebar. Penghapusan permanen hanya
 * lewat "Reset Semua Sesi" di /settings, sesuai desain zona berbahaya.
 */
export function useChat(
  initialSessionId?: string,
  initialTitle = "",
): ChatController {
  const queryClient = useQueryClient();
  const abortRef = useRef<AbortController | null>(null);

  const [sessionId, setSessionId] = useState<string | null>(initialSessionId ?? null);
  const [sessionTitle, setSessionTitle] = useState(initialTitle);
  const [messages, setMessages] = useState<UiMessage[]>([]);
  const [isLoadingHistory, setIsLoadingHistory] = useState(Boolean(initialSessionId));
  const [historyError, setHistoryError] = useState<unknown>(null);
  const [isSending, setIsSending] = useState(false);
  const [lastQuestion, setLastQuestion] = useState<string | null>(null);
  const [rateLimit, setRateLimit] = useState<ChatController["rateLimit"]>(null);
  const rateLimitTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Muat histori saat sesi yang dibuka berubah. Komponen di-key oleh
  // sessionId di halaman, jadi state awal sudah benar saat effect ini jalan.
  useEffect(() => {
    if (!initialSessionId) return;
    const controller = new AbortController();

    getHistory(initialSessionId, controller.signal)
      .then((history) => {
        if (controller.signal.aborted) return;
        if (!history) {
          setMessages([]);
          setHistoryError(new ApiError("Sesi tidak ditemukan atau sudah berakhir.", 404));
          return;
        }
        setSessionTitle(history.session.title);
        setMessages(
          history.messages.map((message) => ({
            id: message.id,
            role: message.role,
            content: message.content,
            citations: message.citations ?? [],
            notFound: message.not_found ?? false,
            state: "done" as const,
          })),
        );
      })
      .catch((error) => {
        if (controller.signal.aborted) return;
        setHistoryError(toApiError(error));
      })
      .finally(() => {
        if (!controller.signal.aborted) setIsLoadingHistory(false);
      });

    return () => controller.abort();
  }, [initialSessionId]);

  useEffect(() => {
    return () => {
      abortRef.current?.abort();
      if (rateLimitTimer.current) clearTimeout(rateLimitTimer.current);
    };
  }, []);

  const patchLastAssistant = useCallback((patch: Partial<UiMessage>) => {
    setMessages((current) => {
      if (current.length === 0) return current;
      const last = current[current.length - 1];
      if (last.role !== "assistant") return current;
      const next = [...current];
      next[next.length - 1] = { ...last, ...patch };
      return next;
    });
  }, []);

  /**
   * Dipanggil setelah stream selesai, baik natural maupun karena pengguna
   * menekan stop. Menyelesaikan dua kasus yang bisa menggantung:
   * jawaban kosong saat dihentikan, dan stream yang tutup tanpa event "done".
   */
  const settleAssistant = useCallback((aborted: boolean) => {
    setMessages((current) => {
      const last = current[current.length - 1];
      if (!last || last.role !== "assistant") return current;
      if (last.state !== "thinking" && last.state !== "streaming") return current;

      const next = [...current];
      if (last.state === "thinking" && last.content.length === 0) {
        next[next.length - 1] = aborted
          ? {
              ...last,
              state: "error",
              errorMessage: "Generasi dihentikan sebelum jawaban dimulai.",
            }
          : {
              ...last,
              state: "error",
              errorMessage: "Server menutup koneksi tanpa mengirim jawaban.",
            };
        return next;
      }

      // Jawaban parsial tetap ditampilkan, tapi ditandai selesai supaya
      // pengguna tahu isinya tidak lengkap.
      next[next.length - 1] = { ...last, state: "done" };
      return next;
    });
  }, []);

  const startCooldown = useCallback((seconds: number) => {
    if (rateLimitTimer.current) clearTimeout(rateLimitTimer.current);
    setRateLimit({
      message: "Batas permintaan tercapai.",
      seconds,
    });
    rateLimitTimer.current = setTimeout(() => {
      setRateLimit(null);
    }, seconds * 1000);
  }, []);

  const run = useCallback(
    async (question: string, activeSessionId: string | null) => {
      const controller = new AbortController();
      abortRef.current = controller;
      setIsSending(true);

      const userMessage: UiMessage = {
        id: `local_user_${Date.now()}`,
        role: "user",
        content: question,
        citations: [],
        notFound: false,
        state: "done",
      };
      const assistantId = `local_assistant_${Date.now()}`;
      setMessages((current) => [
        ...current,
        userMessage,
        {
          id: assistantId,
          role: "assistant",
          content: "",
          citations: [],
          notFound: false,
          state: "thinking",
        },
      ]);

      const applyEvent = (event: import("@/types/api").ChatStreamEvent) => {
        switch (event.type) {
          case "session":
            setSessionId(event.session_id);
            queryClient.invalidateQueries({ queryKey: queryKeys.sessions });
            break;
          case "token":
            setMessages((current) => {
              const next = [...current];
              const last = next[next.length - 1];
              if (!last || last.id !== assistantId) return current;
              next[next.length - 1] = { ...last, content: last.content + event.value, state: "streaming" };
              return next;
            });
            break;
          case "citations":
            patchLastAssistant({ citations: event.value });
            break;
          case "not_found":
            patchLastAssistant({
              notFound: true,
              content:
                "Informasi ini tidak ditemukan dalam dokumen yang diunggah. "
                + "Coba dengan istilah yang dipakai di dalam dokumen, atau periksa daftar dokumen.",
              state: "done",
            });
            break;
          case "error":
            patchLastAssistant({
              state: "error",
              errorMessage: event.message,
            });
            if (event.retry_after_seconds) startCooldown(event.retry_after_seconds);
            break;
          case "done":
            patchLastAssistant({ state: "done" });
            queryClient.invalidateQueries({ queryKey: queryKeys.documents });
            queryClient.invalidateQueries({ queryKey: queryKeys.sessions });
            break;
        }
      };

      try {
        await askQuestion(
          { sessionId: activeSessionId, question },
          { onEvent: applyEvent, signal: controller.signal },
        );
      } catch (error) {
        const apiError = toApiError(error);
        if (!controller.signal.aborted) {
          patchLastAssistant({ state: "error", errorMessage: apiError.message });
          if (apiError.isRateLimited) {
            startCooldown(apiError.retryAfterSeconds ?? 30);
          }
        }
      } finally {
        if (abortRef.current === controller) abortRef.current = null;
        setIsSending(false);
        settleAssistant(controller.signal.aborted);
      }
    },
    [patchLastAssistant, queryClient, settleAssistant, startCooldown],
  );

  const send = useCallback(
    (question: string) => {
      const trimmed = question.trim();
      if (trimmed.length === 0 || isSending) return;
      setRateLimit(null);
      setLastQuestion(trimmed);
      void run(trimmed, sessionId);
    },
    [isSending, run, sessionId],
  );

  const stop = useCallback(() => {
    abortRef.current?.abort();
  }, []);

  const retry = useCallback(() => {
    if (!lastQuestion) return;
    // Hapus pesan gagal terakhir sebelum mengulang agar tidak ada duplikat.
    setMessages((current) => {
      const last = current[current.length - 1];
      if (last?.role === "assistant" && last.state === "error") {
        const next = current.slice(0, -2);
        return next.length > 0 ? next : current;
      }
      return current;
    });
    void run(lastQuestion, sessionId);
  }, [lastQuestion, run, sessionId]);

  const startNewSession = useCallback(() => {
    abortRef.current?.abort();
    setSessionId(newSessionId());
    setSessionTitle("");
    setMessages([]);
    setLastQuestion(null);
    setRateLimit(null);
  }, []);

  /** Dipanggil setelah ubah nama berhasil, supaya judul di header ikut. */
  const setTitle = useCallback((title: string) => {
    setSessionTitle(title);
  }, []);

  const refreshHistory = useCallback(() => {
    queryClient.invalidateQueries({ queryKey: queryKeys.sessions });
  }, [queryClient]);

  return {
    messages,
    sessionId,
    sessionTitle,
    isLoadingHistory,
    isSending,
    historyError,
    rateLimit,
    send,
    stop,
    retry,
    startNewSession,
    setTitle,
    refreshHistory,
  };
}
