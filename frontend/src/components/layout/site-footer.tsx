import Link from "next/link";
import { Logo } from "@/components/brand/logo";
import packageJson from "../../../package.json";

/**
 * Versi dibaca dari package.json, bukan ditulis manual di markup, supaya
 * angka di footer selalu sama dengan yang benar-benar ter-deploy.
 */
const VERSION: string = packageJson.version;

export function SiteFooter() {
  return (
    <footer className="mt-auto border-t border-border bg-card">
      <div className="mx-auto flex w-full max-w-[1200px] flex-col gap-2 px-4 py-5 sm:flex-row sm:items-center sm:justify-between sm:px-6">
        <p className="flex items-center gap-2 text-[12px] text-muted-foreground">
          <Logo size={16} markOnly />
          <span>
            <span className="font-medium text-foreground">Intelligent Document Assistant</span>
            {" · Platform tanya-jawab berbasis dokumen"}
          </span>
        </p>
        <p className="flex items-center gap-4 text-[12px] text-muted-foreground">
          <Link href="/about" className="rounded hover:text-foreground hover:underline">
            Tentang &amp; arsitektur
          </Link>
          <span className="font-mono tnum">v{VERSION}</span>
          <span>Hak cipta (c) 2026 PogungSoftwareHouseTeam (PSHT). Seluruh hak dilindungi.</span>
        </p>
      </div>
    </footer>
  );
}
