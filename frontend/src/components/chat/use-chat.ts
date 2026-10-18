"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import {
  askQuestion,
  getHistory,
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
  /**
   * Jawaban ini datang dari pengetahuan umum model, bukan dari dokumen.
   * UI wajib menandainya; menyembunyikan fakta ini membuat pengguna mengira
   * jawabannya bersumber pada dokumennya.
   */
  ungrounded?: boolean;
  state: MessageState;
  errorMessage?: string;
}

export interface ChatController {
  messages: UiMessage[];
  sessionId: string | null;
  /**
   * Scope dokumen sesi ini, dibaca dari data sesi yang tersimpan.
   *
   * Dipakai sebagai sumber utama saat mengirim pertanyaan lanjutan. Kalau
   * nilainya bergantung pada daftar sesi yang mungkin belum termuat, scope
   * bisa jatuh menjadi null dan pertanyaan mencari di seluruh dokumen.
   */
  sessionDocumentId: string | null;
  /**
   * Scope beberapa dokumen, dibaca dari data sesi yang tersimpan.
   *
   * Dipisah dari sessionDocumentId karena artinya berbeda: sesi satu
   * dokumen menampilkan nama berkasnya, sedangkan sesi multi-dokumen hanya
   * menampilkan jumlah. Menggabungkan keduanya membuat UI harus menebak mana
   * yang sedang berlaku.
   */
  sessionDocumentIds: string[];
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
  options: {
    /** Scope dokumen untuk sesi baru (chat privat per dokumen). */
    documentId?: string | null;
    /** Scope beberapa dokumen untuk sesi baru. */
    documentIds?: string[];
    /** Izinkan LLM menjawab dari pengetahuan umum saat konteks kosong. */
    allowUngrounded?: boolean;
  } = {},
): ChatController {
  const queryClient = useQueryClient();
  const abortRef = useRef<AbortController | null>(null);

  const [sessionId, setSessionId] = useState<string | null>(initialSessionId ?? null);
  // Scope sesi yang sedang dibuka. Diisi dari riwayat sesi (server), bukan
  // dari daftar sesi yang bisa belum termuat.
  const [sessionDocumentId, setSessionDocumentId] = useState<string | null>(null);
  // Scope jamak sesi yang sedang dibuka. Diisi dari riwayat sesi, sama
  // seperti scope tunggal, supaya pertanyaan lanjutan tidak melebar.
  const [sessionDocumentIds, setSessionDocumentIds] = useState<string[]>([]);
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
        // Scope sesi datang dari data sesi yang tersimpan, jadi pertanyaan
        // lanjutan memakai dokumen yang sama tanpa bergantung pada daftar
        // sesi yang mungkin belum termuat.
        setSessionDocumentId(history.session.document_id ?? null);
        setSessionDocumentIds(history.session.document_ids ?? []);
        setMessages(
          history.messages.map((message) => ({
            id: message.id,
            role: message.role,
            content: message.content,
            citations: message.citations ?? [],
            notFound: message.not_found ?? false,
            // Label "bukan dari dokumen" harus ikut saat riwayat dibuka lagi.
            // Kalau hilang setelah reload, jawaban lama terlihat bersumber
            // padahal tidak.
            ungrounded: message.ungrounded ?? false,
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
          case "ungrounded":
            // Ditandai sebelum token pertama dirender, supaya labelnya tidak
            // muncul terlambat di bawah jawaban yang sudah terbaca.
            patchLastAssistant({ ungrounded: true });
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
            // Tabel log di /analytics baru di-refetch saat halaman dibuka, jadi
            // pertanyaan yang baru saja selesai tidak terlihat sampai user
            // memuat ulang halaman.
            queryClient.invalidateQueries({ queryKey: ["analytics", "logs"] });
            break;
        }
      };

      try {
        // Scope ditentukan dari state hook ini, bukan dari prop yang bisa
        // berubah: sesi yang sudah dibuka memakai scope sesinya, sesi baru
        // memakai scope dari `?doc=`. Server tetap memverifikasi ulang, jadi
        // nilai di sini hanya optimisasi, kebenarannya ada di backend.
        const scopeForRequest = activeSessionId
          ? sessionDocumentId
          : (options.documentId ?? null);
        // Scope jamak hanya berlaku untuk sesi baru. Untuk sesi yang sudah
        // berjalan, scope-nya diambil dari riwayat di server, supaya klien
        // yang lupa mengirimnya tidak memperlebar pencarian.
        const scopeIdsForRequest = activeSessionId
          ? sessionDocumentIds
          : (options.documentIds ?? []);
        await askQuestion(
          {
            sessionId: activeSessionId,
            question,
            documentId: scopeForRequest,
            documentIds: scopeIdsForRequest,
            allowUngrounded: options.allowUngrounded ?? false,
          },
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
    [
      patchLastAssistant,
      queryClient,
      settleAssistant,
      startCooldown,
      sessionDocumentId,
      sessionDocumentIds,
      options.documentId,
      options.documentIds,
      options.allowUngrounded,
    ],
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
    // Selalu potong dua pesan terakhir, termasuk kalau hasilnya kosong.
    // Kalau array kosong dikembalikan apa adanya, bubble error lama tetap
    // tampil berdampingan dengan pertanyaan ulang.
    setMessages((current) => {
      const last = current[current.length - 1];
      if (last?.role === "assistant" && last.state === "error") {
        return current.slice(0, -2);
      }
      return current;
    });
    void run(lastQuestion, sessionId);
  }, [lastQuestion, run, sessionId]);

const startNewSession = useCallback(() => {
    abortRef.current?.abort();
    // Sesi baru = belum ada id sama sekali. Kalau di sini dibuat id lokal,
    // halaman langsung mencoba memuat histori id itu yang belum pernah ada,
    // dan pengguna langsung melihat layar "sesi tidak ditemukan".
    // Id asli datang dari event `session` pada pertanyaan pertama.
    setSessionId(null);
    // Scope dilepas juga. Kalau tidak, sesi baru mewarisi dokumen sesi
    // sebelumnya, pengguna mengira mulai dari nol, tapi pertanyaannya
    // masih terkunci ke dokumen lama.
    setSessionDocumentId(null);
    setSessionDocumentIds([]);
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
    sessionDocumentId,
    sessionDocumentIds,
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
