import type { Metadata } from "next";
import { Logo } from "@/components/brand/logo";
import { devPasscodeHint } from "@/lib/auth/session";
import { safeNextPath } from "@/lib/api/origin";
import { isDemoEntryEnabled } from "@/lib/demo/profile";
import { LoginForm } from "./login-form";

export const metadata: Metadata = {
  title: "Akses Sistem",
  description: "Masukkan passcode untuk membuka workspace dokumen.",
};

/**
 * Halaman ini membaca `searchParams`, jadi dirender per permintaan.
 *
 * Penanda ini menyatakan maksud kode, bukan tambalan untuk kegagalan build:
 * halaman yang isinya bergantung pada `?next=` tidak bisa dibekukan saat
 * build, karena nilai itu belum ada pada waktu itu.
 */
export const dynamic = "force-dynamic";

export default async function LoginPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  // `next` berasal dari URL, jadi divalidasi di server (open redirect).
  const params = await searchParams;
  const rawNext = Array.isArray(params.next) ? params.next[0] : params.next;

  return (
    <main className="flex min-h-dvh items-center justify-center bg-background px-4 py-12">
      <div className="w-full max-w-[400px]">
        <div className="overflow-hidden rounded-lg bg-card ring-1 ring-border">
          <div className="h-0.5 bg-primary" aria-hidden />

          <div className="flex flex-col gap-6 p-8">
            <div className="flex flex-col items-center gap-3 text-center">
              <Logo size={52} />
              <p className="eyebrow">Akses demo</p>
              {isDemoEntryEnabled ? (
                <>
                  <h1 className="text-2xl font-semibold tracking-tight">Masuk ke demo</h1>
                  <p className="max-w-80 text-[13px] leading-relaxed text-muted-foreground">
                    Demo portofolio dengan data contoh. Pencarian berbasis kata dan
                    jawaban berupa kutipan; data hanya tersimpan di peramban ini.
                  </p>
                </>
              ) : (
                <>
                  <h1 className="text-2xl font-semibold tracking-tight">
                    Masuk untuk melanjutkan
                  </h1>
                  <p className="max-w-80 text-[13px] leading-relaxed text-muted-foreground">
                    Masukkan passcode akses untuk memakai workspace dokumen ini.
                  </p>
                </>
              )}
            </div>

            <LoginForm
              devHint={devPasscodeHint()}
              nextPath={safeNextPath(rawNext)}
              demoEnabled={isDemoEntryEnabled}
            />
          </div>
        </div>

        <p className="mt-6 text-center text-[12px] text-muted-foreground">
          Demo portofolio. Butuh akses? Hubungi penyedia demo.
        </p>
      </div>
    </main>
  );
}