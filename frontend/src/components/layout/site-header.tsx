"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { BarChart3, FileText, LogOut, MessageSquare, Settings } from "lucide-react";
import { Logo, Wordmark } from "@/components/brand/logo";
import { Button } from "@/components/ui/button";
import { getHealth } from "@/lib/api";
import { isMockMode } from "@/lib/api/config";

/**
 * Navigasi utama sengaja hanya berisi rute yang benar-benar ada
 *. Halaman analitik dan pengaturan juga dijangkau lewat footer
 * sidebar /chat, bukan lewat navbar, supaya navbar tetap pendek.
 */
const NAV = [
  { href: "/chat", label: "Chat", Icon: MessageSquare },
  { href: "/documents", label: "Dokumen", Icon: FileText },
  { href: "/analytics", label: "Analitik", Icon: BarChart3 },
  { href: "/settings", label: "Pengaturan", Icon: Settings },
] as const;

export function SiteHeader() {
  const pathname = usePathname();

  // Status backend hanya dicek saat terhubung ke FastAPI sungguhan.
  // Di mode demo, banner demo di bawah yang berlaku, bukan banner ini.
  const health = useQuery({
    queryKey: ["health"],
    queryFn: ({ signal }) => getHealth(signal),
    enabled: !isMockMode,
    refetchInterval: 60_000,
    retry: false,
  });
  const degraded = !isMockMode
    && health.data
    && (health.data.status === "degraded" || health.data.fallback?.mode === "reduced");

  /**
   * Indeks dibangun dengan model embedding yang berbeda dari yang aktif.
   *
   * Ditampilkan lebih dulu daripada peringatan mode terbatas, karena
   * akibatnya lebih serius: retrieval tetap berjalan tanpa error, tapi
   * jawabannya ngawur. Tanpa penanda ini, satu-satunya petunjuk ada di log
   * server, dan gejalanya mudah disalahartikan sebagai "dokumennya aneh".
   */
  const embeddingMismatch = !isMockMode ? health.data?.fallback?.embedding_mismatch : undefined;

  return (
    // Blur dipakai di sini dan di sticky input chat, dua elemen yang memang
    // menumpuk di atas konten yang bergulir. Tujuannya biar teks di bawahnya
    // tidak ikut terbaca, bukan untuk gaya.
    <header className="sticky top-0 z-40 border-b border-border bg-card/90 backdrop-blur-sm">
      <div className="mx-auto flex h-14 w-full max-w-[1200px] items-center gap-6 px-4 sm:px-6">
        <Link
          href="/chat"
          className="flex items-center gap-2.5 rounded-md py-1"
          aria-label="Intelligent Document Assistant, beranda"
        >
          <Logo size={28} />
          <Wordmark className="hidden sm:inline" />
        </Link>

        <nav aria-label="Navigasi utama" className="ml-auto">
          <ul className="flex items-center gap-1">
            {NAV.map(({ href, label }) => {
              const active = pathname === href || pathname.startsWith(`${href}/`);
              return (
                <li key={href}>
                  <Link
                    href={href}
                    aria-current={active ? "page" : undefined}
                    className={`relative rounded-md px-3 py-1.5 text-[13px] font-medium transition-colors ${
                      active ? "text-foreground" : "text-muted-foreground hover:text-foreground"
                    }`}
                  >
                    {label}
                    {/* Penanda aktif: garis navy di bawah label. Satu-satunya
                        tempat brand navy muncul di navbar. */}
                    {active ? (
                      <span
                        className="absolute inset-x-3 -bottom-[13px] h-0.5 rounded-full bg-primary"
                        aria-hidden
                      />
                    ) : null}
                  </Link>
                </li>
              );
            })}
          </ul>
        </nav>

        <div className="flex items-center gap-1">
          <form action="/api/logout" method="post">
            <Button type="submit" variant="ghost" size="icon-sm" aria-label="Keluar dari demo">
              <LogOut className="size-4" aria-hidden />
            </Button>
          </form>
        </div>
      </div>

      {isMockMode ? (
        <p className="border-t border-border bg-brand-wash px-4 py-1.5 text-center text-[12px] text-brand-ink">
          Jawaban diambil dari dokumen yang Anda unggah. Semua data tersimpan di peramban ini.
        </p>
      ) : null}
      {embeddingMismatch ? (
        <p
          role="alert"
          className="border-t border-destructive/30 bg-destructive/10 px-4 py-2 text-center text-[12px] leading-relaxed text-destructive"
        >
          <span className="font-medium">Indeks dokumen tidak cocok dengan model embedding yang aktif.</span>{" "}
          {embeddingMismatch}
        </p>
      ) : null}
      {degraded ? (
        <p className="border-t border-border bg-warning/10 px-4 py-1.5 text-center text-[12px] text-warning-ink">
          Backend berjalan dalam mode terbatas ({health.data?.fallback?.vector_store ?? "storage"}
          {health.data?.fallback?.vector_store_persistent === false ? ", tidak persisten" : ""}).
          Data bisa hilang saat restart, cek
          <Link href="/analytics" className="mx-1 underline underline-offset-2 hover:no-underline">
            analitik
          </Link>
          atau endpoint /api/v1/health.
        </p>
      ) : null}
    </header>
  );
}
