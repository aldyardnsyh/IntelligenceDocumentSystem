"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Database, Loader2, RotateCcw, Trash2, TriangleAlert } from "lucide-react";
import { notify } from "@/lib/notify";
import { Button } from "@/components/ui/button";
import { Slider } from "@/components/ui/slider";
import { ConfirmDialog } from "@/components/common/confirm-dialog";
import { ErrorState } from "@/components/common/error-state";
import { getSettings, resetAllSessions, resetDemoData, updateSettings } from "@/lib/api";
import { isMockMode } from "@/lib/api/config";
import { queryKeys } from "@/lib/queries";
import { ApiError } from "@/lib/api/error";
import type { RetrievalSettings } from "@/types/api";

/**
 * Batas slider dan nilai default.
 *
 * Di produksi angka di sini harus sama dengan `Settings` di backend
 * (`app/core/config.py`). Kalau berbeda, slider menampilkan nilai yang tidak
 * sedang aktif: pengguna melihat 0.75 sementara server memakai 0.5, lalu
 * menggeser control yang tidak memberi efek. Backend yang meng-klem nilai
 * di luar rentang, jadi batas slider di sinilah yang harus sinkron.
 *
 * Di demo skalanya lain: skor chunk adalah cakupan kata pertanyaan yang
 * ditemukan di chunk (0..1), bukan cosine similarity vektor. Selain itu sebuah
 * chunk baru dipakai sebagai sumber bila minimal dua kata pertanyaan cocok.
 * Karena itu ambang yang masuk akal ada di 0.20-0.60, dan memakai rentang
 * produksi di sini akan menolak pertanyaan yang sebenarnya terjawab oleh
 * dokumen contoh.
 */
const LIMITS = {
  top_k: { min: 3, max: 10, step: 1 },
  // Produksi: rentang mengikuti `min_similarity_threshold`/
  // `max_similarity_threshold` di backend, diukur untuk `multilingual-e5-small`.
  // Demo: skor berupa cakupan kata, bukan cosine, jadi ambangnya 0.20-0.60.
  similarity_threshold: isMockMode
    ? { min: 0.2, max: 0.6, step: 0.01 }
    : { min: 0.75, max: 0.92, step: 0.01 },
} as const;

/** Titik seimbang pada skala yang sedang aktif; hanya label, bukan default. */
const BALANCED_THRESHOLD = isMockMode ? "0.40" : "0.84";

const DEFAULTS: RetrievalSettings = {
  top_k: 5,
  // Demo 0.25: pencocokan kata memberi skor lebih rendah daripada cosine,
  // apalagi pada pertanyaan panjang. Syarat minimal dua kata cocok yang
  // menjaga sitasi tetap relevan.
  similarity_threshold: isMockMode ? 0.25 : 0.82,
};

export function SettingsView() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const [draft, setDraft] = useState<RetrievalSettings | null>(null);
  const [seededFrom, setSeededFrom] = useState<RetrievalSettings | null>(null);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [demoConfirmOpen, setDemoConfirmOpen] = useState(false);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const settings = useQuery({
    queryKey: queryKeys.settings,
    queryFn: ({ signal }) => getSettings(signal),
  });

  // Penyesuaian state saat props berubah (pola yang direkomendasikan React):
  // draft diambil satu kali dari hasil server, lalu danach menjadi milik
  // pengguna sampai ada respons baru.
  if (settings.data && settings.data !== seededFrom) {
    setSeededFrom(settings.data);
    setDraft(settings.data);
  }

  const saveMutation = useMutation({
    mutationFn: (patch: Partial<RetrievalSettings>) => updateSettings(patch),
    onSuccess: (saved) => {
      queryClient.setQueryData(["settings"], saved);
      setDraft(saved);
      notify.success(
        "Pengaturan disimpan",
        "Nilai baru dipakai pada pertanyaan berikutnya. Jawaban yang sudah di-cache "
          + "tidak terpengaruh.",
      );
    },
    onError: (error) => {
      notify.error(error instanceof ApiError ? error.message : "Pengaturan gagal disimpan.")
    },
  });

  const resetMutation = useMutation({
    mutationFn: () => resetAllSessions(),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.sessions });
      notify.success(
        "Seluruh sesi dihapus",
        "Riwayat percakapan dan cache jawabannya sudah dibersihkan.",
      );
      router.push("/chat");
    },
    onError: (error) => {
      notify.error(error instanceof ApiError ? error.message : "Sesi gagal direset.")
    },
  });

  /**
   * Reset penuh fixture demo.
   *
   * Selain dokumen dan riwayat, `reset()` di fixture juga mengembalikan
   * pengaturan retrieval ke seed. Karena itu query settings ikut
   * di-invalidasi: tanpa itu slider di halaman ini tetap menampilkan nilai
   * sebelum reset, lalu penyimpanan berikutnya menulis balik angka lama.
   */
  const demoResetMutation = useMutation({
    mutationFn: () => resetDemoData(),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.documents });
      queryClient.invalidateQueries({ queryKey: queryKeys.sessions });
      // Awalan ["analytics"] mencakup ringkasan sekaligus semua halaman log.
      queryClient.invalidateQueries({ queryKey: ["analytics"] });
      queryClient.invalidateQueries({ queryKey: queryKeys.settings });
      notify.success("Data demo dikembalikan ke kondisi awal.");
    },
    onError: (error) => {
      notify.error(error instanceof ApiError ? error.message : "Data demo gagal direset.")
    },
  });

  // Penyimpanan otomatis dengan debounce 800ms: mengubah slider terasa langsung
  // tanpa mengetik ulang, tapi tidak menembak API tiap gerakan.
// Patch yang belum dikirim digabung, bukan ditimpa. Kalau tidak, mengubah
  // top-k lalu threshold dalam jendela 800 ms membuat perubahan top-k hilang
  // tanpa jejak: timer berikutnya hanya membawa satu kunci.
  const pendingPatchRef = useRef<Partial<RetrievalSettings>>({});

  const scheduleSave = (patch: Partial<RetrievalSettings>) => {
    pendingPatchRef.current = { ...pendingPatchRef.current, ...patch };
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => {
      const merged = pendingPatchRef.current;
      pendingPatchRef.current = {};
      saveMutation.mutate(merged);
    }, 800);
  };

  useEffect(() => {
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
  }, []);

  if (settings.isPending) {
    return (
      <div className="mx-auto flex w-full max-w-[640px] flex-1 flex-col gap-4" aria-hidden>
        {[0, 1, 2].map((index) => (
          <div key={index} className="h-44 rounded-lg bg-card ring-1 ring-border" />
        ))}
      </div>
    );
  }

  if (settings.isError || !draft) {
    return (
      <div className="mx-auto w-full max-w-[640px] flex-1">
        <ErrorState error={settings.error} onRetry={() => settings.refetch()} />
      </div>
    );
  }

  const topKChanged = draft.top_k !== (settings.data?.top_k ?? draft.top_k);
  const thresholdChanged =
    draft.similarity_threshold !== (settings.data?.similarity_threshold ?? draft.similarity_threshold);
  const dirty = topKChanged || thresholdChanged;

  return (
    <div className="mx-auto flex w-full max-w-[640px] flex-1 flex-col gap-4">
      <header className="flex flex-col gap-1.5">
        <p className="eyebrow">Konfigurasi</p>
        <h1 className="text-2xl font-semibold tracking-tight">Pengaturan Sistem</h1>
        <p className="text-[13px] leading-relaxed text-muted-foreground">
          Parameter retrieval berlaku pada pertanyaan berikutnya tanpa perlu
          memulai ulang layanan.
        </p>
      </header>

      <section className="flex flex-col gap-6 rounded-lg bg-card p-5 ring-1 ring-border">
        <div className="flex flex-col gap-1">
          <h2 className="text-[15px] font-semibold">Parameter retrieval</h2>
          <p className="text-[13px] text-muted-foreground">
            Dua angka ini menentukan berapa konteks yang diteruskan ke model dan
            seberapa mirip sebuah chunk harus agar dianggap relevan.
          </p>
        </div>

        <div className="flex flex-col gap-2.5">
          <div className="flex items-baseline justify-between gap-4">
            <label htmlFor="top-k" className="text-[13px] font-medium">
              Jumlah sumber diambil (top-k)
            </label>
            <span className="rounded-md bg-primary px-2 py-0.5 font-mono text-[12px] text-primary-foreground tnum">
              {draft.top_k}
            </span>
          </div>
          <Slider
            id="top-k"
            value={[draft.top_k]}
            min={LIMITS.top_k.min}
            max={LIMITS.top_k.max}
            step={LIMITS.top_k.step}
            onValueChange={(value) => {
              const next = Array.isArray(value) ? value[0] : value;
              if (next === undefined) return;
              setDraft((current) => (current ? { ...current, top_k: next } : current));
              scheduleSave({ top_k: next });
            }}
            aria-label="Jumlah sumber diambil"
          />
          <p className="text-[12px] leading-relaxed text-muted-foreground">
            Semakin tinggi, semakin banyak konteks yang dipakai, tetapi jawaban
            bisa kurang fokus. Rentang {LIMITS.top_k.min} sampai {LIMITS.top_k.max}.
          </p>
        </div>

        <div className="flex flex-col gap-2.5">
          <div className="flex items-baseline justify-between gap-4">
            <label htmlFor="threshold" className="text-[13px] font-medium">
              Ambang kemiripan
            </label>
            <span className="rounded-md bg-primary px-2 py-0.5 font-mono text-[12px] text-primary-foreground tnum">
              {draft.similarity_threshold.toFixed(2)}
            </span>
          </div>
          <Slider
            id="threshold"
            value={[draft.similarity_threshold]}
            min={LIMITS.similarity_threshold.min}
            max={LIMITS.similarity_threshold.max}
            step={LIMITS.similarity_threshold.step}
            onValueChange={(value) => {
              const next = Array.isArray(value) ? value[0] : value;
              if (next === undefined) return;
              setDraft((current) =>
                current ? { ...current, similarity_threshold: next } : current,
              );
              scheduleSave({ similarity_threshold: next });
            }}
            aria-label="Ambang kemiripan minimum"
          />
          <div className="flex justify-between text-[11px] text-muted-foreground tnum">
            <span>{LIMITS.similarity_threshold.min.toFixed(2)} longgar</span>
            <span>{BALANCED_THRESHOLD} seimbang</span>
            <span>{LIMITS.similarity_threshold.max.toFixed(2)} ketat</span>
          </div>
          <p className="text-[12px] leading-relaxed text-muted-foreground">
            Batas skor minimum agar sebuah chunk dipakai sebagai sumber.{" "}
            {isMockMode
              ? "Di demo ini skor dihitung dari kecocokan kata pertanyaan dengan isi chunk, jadi pertanyaan yang jawabannya ada biasanya berskor 0.45-0.70. Di produksi skor berasal dari kemiripan vektor, yang angkanya lebih tinggi."
              : "Di produksi skor berasal dari kemiripan vektor: pertanyaan relevan biasanya berskor 0.84-0.91, yang tidak relevan 0.72-0.81. Di demo ini skor dihitung dari kecocokan kata, bukan kemiripan vektor."}{" "}
            Semakin tinggi, semakin sering sistem menjawab &ldquo;tidak
            ditemukan&rdquo;.
          </p>
        </div>

        {dirty ? (
          <p className="flex items-center gap-1.5 text-[12px] text-muted-foreground">
            <Loader2 className="size-3 animate-spin" aria-hidden />
            Menyimpan...
          </p>
        ) : null}
      </section>

      {/*
        Zona berbahaya dibedakan dengan border merah, bukan fill merah penuh:
        "hapus permanen" adalah informasi yang harus terbaca jelas, bukan
        dekorasi yang menutupi teksnya sendiri.
      */}
      <section className="flex flex-col gap-4 rounded-lg border border-destructive/35 bg-card p-5">
        <div className="flex items-start gap-2.5">
          <TriangleAlert className="mt-0.5 size-4 shrink-0 text-destructive" aria-hidden />
          <div className="flex flex-col gap-1">
            <h2 className="text-[15px] font-semibold text-destructive">Zona berbahaya</h2>
            <p className="text-[13px] leading-relaxed text-muted-foreground">
              Tindakan di bawah menghapus data secara permanen dan tidak bisa
              dibatalkan.
            </p>
          </div>
        </div>

        <div className="flex flex-col gap-2">
          <p className="text-[13px] font-medium">Reset semua sesi percakapan</p>
          <p className="text-[12px] leading-relaxed text-muted-foreground">
            Menghapus seluruh riwayat percakapan dari memori sesi. Dokumen dan
            indeksnya tidak terpengaruh.
          </p>
          <Button
            variant="destructive"
            className="w-fit gap-1.5"
            disabled={resetMutation.isPending}
            onClick={() => setConfirmOpen(true)}
          >
            <Trash2 className="size-4" aria-hidden />
            Reset semua sesi percakapan
          </Button>
        </div>
      </section>

      {/*
        Kartu ini hanya muncul di mode demo. Di backend tidak ada data contoh
        yang bisa dikembalikan, jadi menampilkannya akan menawarkan tombol yang
        selalu gagal.
      */}
      {isMockMode ? (
        <section className="flex flex-col gap-4 rounded-lg bg-card p-5 ring-1 ring-border">
          <div className="flex flex-col gap-1">
            <h2 className="text-[15px] font-semibold">Reset data demo</h2>
            <p className="text-[13px] leading-relaxed text-muted-foreground">
              Menghapus dokumen yang Anda unggah, riwayat percakapan, dan catatan
              aktivitas. Tiga dokumen contoh dikembalikan seperti semula.
            </p>
          </div>
          <Button
            variant="destructive"
            className="w-fit gap-1.5"
            disabled={demoResetMutation.isPending}
            onClick={() => setDemoConfirmOpen(true)}
          >
            <Database className="size-4" aria-hidden />
            Reset data demo
          </Button>
        </section>
      ) : null}

      <div className="flex flex-wrap items-center justify-between gap-3 pb-4">
        <Button
          variant="ghost"
          className="gap-1.5"
          disabled={!dirty}
          onClick={() => {
            setDraft(DEFAULTS);
            scheduleSave(DEFAULTS);
          }}
        >
          <RotateCcw className="size-4" aria-hidden />
          Kembalikan nilai awal
        </Button>
        <p className="text-[12px] text-muted-foreground">
          Perubahan disimpan otomatis sekitar 0,8 detik setelah slider berhenti.
        </p>
      </div>

      <ConfirmDialog
        open={confirmOpen}
        onOpenChange={setConfirmOpen}
        title="Reset semua sesi percakapan?"
        description="Seluruh riwayat percakapan akan dihapus permanen dari memori sesi. Tindakan ini tidak dapat dibatalkan."
        confirmLabel="Hapus semua sesi"
        onConfirm={() => resetMutation.mutateAsync()}
      />

      <ConfirmDialog
        open={demoConfirmOpen}
        onOpenChange={setDemoConfirmOpen}
        title="Reset data demo?"
        description="Semua dokumen unggahan dan riwayat percakapan di peramban ini akan dihapus. Tindakan ini tidak bisa dibatalkan."
        confirmLabel="Ya, reset data"
        cancelLabel="Batal"
        onConfirm={() => demoResetMutation.mutateAsync()}
      />
    </div>
  );
}
