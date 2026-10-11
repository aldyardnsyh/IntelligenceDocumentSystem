"use client";

import { Toaster as Sonner, type ToasterProps } from "sonner";
import {
  CircleCheckIcon,
  InfoIcon,
  Loader2Icon,
  OctagonXIcon,
  TriangleAlertIcon,
} from "lucide-react";

/**
 * Notifikasi dengan empat jenis yang benar-benar berbeda.
 *
 * Sebelumnya semua jenis memakai gaya yang sama: latar putih, ikon abu-abu,
 * dan warna teks default. Akibatnya "berhasil" dan "gagal" terlihat identik
 * sekilas, pengguna harus membaca teksnya untuk tahu apa yang terjadi.
 *
 * Di sini setiap jenis punya warna, ikon, dan latar sendiri:
 * - sukses  : hijau, ikon centang
 * - error   : merah, ikon silang
 * - warning : oranye, ikon segitiga
 * - info    : biru brand, ikon informasi
 *
 * Warna diambil dari token yang sudah ada di globals.css, jadi tidak ada
 * nilai hex yang ditulis ulang di sini dan kontras teks tetap terjaga.
 */

const Toaster = ({ ...props }: ToasterProps) => {
  return (
    <Sonner
      theme="light"
      className="toaster group"
      // Deskripsi ditampilkan sebagai baris kedua, bukan disamarkan di
      // tooltip: pesan singkat di judul, detail di bawahnya.
      closeButton
      richColors={false}
      icons={{
        success: <CircleCheckIcon className="size-4" />,
        info: <InfoIcon className="size-4" />,
        warning: <TriangleAlertIcon className="size-4" />,
        error: <OctagonXIcon className="size-4" />,
        loading: <Loader2Icon className="size-4 animate-spin" />,
      }}
      toastOptions={{
        classNames: {
          toast:
            "cn-toast group toast flex w-full items-start gap-3 rounded-lg border px-4 py-3 shadow-lg",
          title: "text-[13px] font-semibold leading-snug",
          description: "text-[12px] leading-relaxed opacity-90",
          icon: "mt-0.5 shrink-0",
          closeButton: "border-border bg-card text-foreground",
          // Empat jenis, empat gaya. Kelasnya ditulis eksplisit supaya warna
          // tidak bergantung pada tema bawaan pustaka.
          success:
            "border-success/30 bg-success/10 text-success-ink [&_[data-icon]]:text-success-ink",
          error:
            "border-destructive/30 bg-destructive/10 text-destructive [&_[data-icon]]:text-destructive",
          warning:
            "border-warning/40 bg-warning/10 text-warning-ink [&_[data-icon]]:text-warning-ink",
          info: "border-brand/30 bg-brand-wash text-brand-ink [&_[data-icon]]:text-brand-ink",
          loading: "border-border bg-card text-foreground",
        },
      }}
      {...props}
    />
  );
};

export { Toaster };