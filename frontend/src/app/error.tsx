"use client";

import { useEffect, useState } from "react";
import { ArrowLeft, Copy, RotateCw, ServerCrash } from "lucide-react";
import { Button } from "@/components/ui/button";
import { LinkButton } from "@/components/common/link-button";

/**
 * Halaman 500 menampilkan digest error yang benar-benar diterima dari Next,
 * bukan id insiden buatan. Informasi diagnostik yang tidak berasal dari sistem
 * yang benar-benar gagal akan membuat teknisi menelusuri ke tempat yang salah.
 */
export default function GlobalError({
  error,
  retry,
}: {
  error: Error & { digest?: string };
  retry: () => void;
}) {
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    console.error(error);
  }, [error]);

  const details = [
    error.digest ? `Digest: ${error.digest}` : null,
    `Waktu: ${new Date().toISOString()}`,
  ].filter(Boolean) as string[];

  const copyDetails = async () => {
    try {
      await navigator.clipboard.writeText(details.join("\n"));
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      setCopied(false);
    }
  };

  return (
    <div className="flex min-h-dvh flex-col items-center justify-center gap-6 bg-background px-4 py-16 text-center">
      <span className="flex size-12 items-center justify-center rounded-lg bg-destructive/10 text-destructive">
        <ServerCrash className="size-6" aria-hidden />
      </span>

      <div className="flex flex-col items-center gap-2">
        <p className="text-[12px] font-semibold tracking-[0.08em] text-destructive uppercase">
          Error 500
        </p>
        <p className="text-[64px] leading-none font-bold tracking-tight text-primary tnum sm:text-[88px]">
          500
        </p>
      </div>

      <div className="flex max-w-lg flex-col gap-2">
        <h1 className="text-2xl font-semibold tracking-tight">
          Terjadi kesalahan pada server
        </h1>
        <p className="text-[14px] leading-relaxed text-muted-foreground">
          Ada bagian halaman ini yang gagal dimuat. Coba muat ulang. Dokumen dan
          riwayat percakapan Anda tidak terpengaruh.
        </p>
      </div>

      <div className="flex flex-wrap justify-center gap-2">
        <Button className="gap-1.5" onClick={retry}>
          <RotateCw className="size-4" aria-hidden />
          Muat ulang
        </Button>
        <LinkButton variant="outline" className="gap-1.5" href="/">
          <ArrowLeft className="size-4" aria-hidden />
          Kembali ke beranda
        </LinkButton>
      </div>

      {error.digest ? (
        <div className="w-full max-w-lg rounded-lg bg-card p-4 text-left ring-1 ring-border">
          <div className="flex items-center justify-between gap-3">
            <p className="eyebrow">Detail teknis</p>
            <Button variant="ghost" size="sm" onClick={copyDetails} className="h-7 gap-1.5">
              <Copy className="size-3.5" aria-hidden />
              {copied ? "Tersalin" : "Salin detail"}
            </Button>
          </div>
          <p className="mt-2 font-mono text-[12px] leading-relaxed text-muted-foreground">
            {details.join("\n")}
          </p>
        </div>
      ) : null}
    </div>
  );
}
