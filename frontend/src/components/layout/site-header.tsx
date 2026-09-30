"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { BarChart3, FileText, LogOut, MessageSquare, Settings } from "lucide-react";
import { Logo, Wordmark } from "@/components/brand/logo";
import { Button } from "@/components/ui/button";
import { isMockMode } from "@/lib/api/config";

/**
 * Navigasi utama sengaja hanya berisi rute yang benar-benar ada
 * (R-24). Halaman analitik dan pengaturan juga dijangkau lewat footer
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
          Mode demo: retrieval berjalan di browser memakai fixture lokal. Isi
          <code className="mx-1 font-mono">NEXT_PUBLIC_API_BASE_URL</code>
          untuk menghubungkan backend FastAPI.
        </p>
      ) : null}
    </header>
  );
}
