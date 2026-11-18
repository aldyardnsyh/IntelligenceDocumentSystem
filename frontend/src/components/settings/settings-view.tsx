"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Trash2, TriangleAlert } from "lucide-react";
import { notify } from "@/lib/notify";
import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/common/confirm-dialog";
import { PipelineFlow } from "@/components/settings/pipeline-flow";
import { resetAllSessions } from "@/lib/api";
import { queryKeys } from "@/lib/queries";
import { ApiError } from "@/lib/api/error";

export function SettingsView() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const [confirmOpen, setConfirmOpen] = useState(false);

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

  return (
    <div className="mx-auto flex w-full max-w-[760px] flex-1 flex-col gap-10 pb-4">
      <header className="flex flex-col gap-1.5">
        <p className="eyebrow">Konfigurasi</p>
        <h1 className="text-2xl font-semibold tracking-tight">Pengaturan Sistem</h1>
        <p className="max-w-[62ch] text-[13px] leading-relaxed text-muted-foreground">
          Halaman ini tidak menawarkan slider. Nilai retrieval dikalibrasi
          lewat evaluasi di backend, karena menggesernya tanpa pengukuran
          hanya menambah tempat salah. Yang ditampilkan adalah jalur yang
          benar-benar dilalui dokumen Anda, dari berkas mentah sampai
          jawaban bersitasi, beserta angka terkininya.
        </p>
      </header>

      <PipelineFlow />

      {/*
        Penjelasan jujur soal parameter yang tidak ada lagi di halaman ini.
        Tanpa ini, pengguna lama yang mencari slider akan mengira fiturnya
        hilang karena bug.
      */}
      <section className="flex flex-col gap-2 rounded-lg bg-card p-5 ring-1 ring-border">
        <h2 className="text-[15px] font-semibold">Di mana parameter retrieval?</h2>
        <p className="text-[13px] leading-relaxed text-muted-foreground">
          top-k, ambang kemiripan, dan reranker tidak diatur dari sini.
          Nilainya diukur terhadap dataset uji lewat halaman{" "}
          <a
            href="/analytics"
            className="rounded font-medium text-brand-ink underline underline-offset-2"
          >
            Analitik
          </a>
          , lalu dikunci di konfigurasi backend. Kalau hasil jawabannya
          menurun, angka di Analitik yang akan menunjukkannya lebih dulu,
          dan penyetelannya dikerjakan di sana, bukan dengan menebak-nebak
          slider.
        </p>
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

      <ConfirmDialog
        open={confirmOpen}
        onOpenChange={setConfirmOpen}
        title="Reset semua sesi percakapan?"
        description="Seluruh riwayat percakapan akan dihapus permanen dari memori sesi. Tindakan ini tidak dapat dibatalkan."
        confirmLabel="Hapus semua sesi"
        onConfirm={() => resetMutation.mutateAsync()}
      />

    </div>
  );
}
