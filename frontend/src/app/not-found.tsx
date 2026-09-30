import type { Metadata } from "next";
import Link from "next/link";
import { ArrowLeft, Compass } from "lucide-react";
import { LinkButton } from "@/components/common/link-button";

export const metadata: Metadata = {
  title: "Halaman tidak ditemukan",
};

/**
 * Saran rute hanya memuat halaman yang benar-benar ada di aplikasi ini.
 * Menautkan ke rute fiktif adalah janji yang tidak bisa ditepati.
 */
const SUGGESTIONS = [
  { href: "/chat", label: "Chat", detail: "Ajukan pertanyaan tentang dokumen" },
  { href: "/documents", label: "Dokumen", detail: "Kelola dokumen sumber" },
  { href: "/analytics", label: "Analitik", detail: "Lihat metrik dan log query" },
  { href: "/about", label: "Tentang", detail: "Baca arsitektur sistem" },
] as const;

export default function NotFound() {
  return (
    <div className="flex min-h-dvh flex-col items-center justify-center gap-6 bg-background px-4 py-16 text-center">
      <div className="flex flex-col items-center gap-2">
        <p className="text-[12px] font-semibold tracking-[0.08em] text-brand-ink uppercase">
          Error 404
        </p>
        <p className="text-[64px] leading-none font-bold tracking-tight text-primary tnum sm:text-[88px]">
          404
        </p>
      </div>

      <div className="flex max-w-lg flex-col gap-2">
        <h1 className="text-2xl font-semibold tracking-tight">Halaman tidak ditemukan</h1>
        <p className="text-[14px] leading-relaxed text-muted-foreground">
          Tautan yang Anda tuju tidak tersedia. Mungkin dokumen sudah dihapus,
          atau alamatnya salah ketik.
        </p>
      </div>

      <LinkButton className="gap-1.5" href="/">
        <ArrowLeft className="size-4" aria-hidden />
        Kembali ke beranda
      </LinkButton>

      <nav aria-label="Halaman lain" className="w-full max-w-lg">
        <p className="eyebrow mb-3">Mungkin Anda mencari</p>
        <ul className="grid grid-cols-1 gap-2 sm:grid-cols-2">
          {SUGGESTIONS.map((item) => (
            <li key={item.href}>
              <Link
                href={item.href}
                className="flex flex-col gap-0.5 rounded-lg bg-card p-3 ring-1 ring-border transition-colors hover:bg-muted"
              >
                <span className="flex items-center gap-1.5 text-[13px] font-medium">
                  <Compass className="size-3.5 text-muted-foreground" aria-hidden />
                  {item.label}
                </span>
                <span className="text-[12px] text-muted-foreground">{item.detail}</span>
              </Link>
            </li>
          ))}
        </ul>
      </nav>
    </div>
  );
}
