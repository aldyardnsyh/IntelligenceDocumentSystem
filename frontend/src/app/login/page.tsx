import type { Metadata } from "next";
import { Logo } from "@/components/brand/logo";
import { devPasscodeHint } from "@/lib/auth/session";
import { LoginForm } from "./login-form";

export const metadata: Metadata = {
  title: "Akses Sistem",
  description: "Masukkan passcode untuk membuka workspace dokumen.",
};

export default function LoginPage() {
  return (
    <main className="flex min-h-dvh items-center justify-center bg-background px-4 py-12">
      <div className="w-full max-w-[400px]">
        <div className="overflow-hidden rounded-lg bg-card ring-1 ring-border">
          <div className="h-0.5 bg-primary" aria-hidden />

          <div className="flex flex-col gap-6 p-8">
            <div className="flex flex-col items-center gap-3 text-center">
              <Logo size={52} />
              <p className="eyebrow">Akses demo</p>
              <h1 className="text-2xl font-semibold tracking-tight">Masuk untuk melanjutkan</h1>
              <p className="max-w-80 text-[13px] leading-relaxed text-muted-foreground">
                Masukkan passcode akses untuk memakai workspace dokumen ini.
              </p>
            </div>

            <LoginForm devHint={devPasscodeHint()} />
          </div>
        </div>

        <p className="mt-6 text-center text-[12px] text-muted-foreground">
          Demo portofolio. Butuh akses? Hubungi penyedia demo.
        </p>
      </div>
    </main>
  );
}
