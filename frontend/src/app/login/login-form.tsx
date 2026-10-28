"use client";

import { useActionState, useEffect, useId, useState } from "react";
import { Eye, EyeOff, Loader2, LogIn } from "lucide-react";
import { Logo } from "@/components/brand/logo";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  enterDemo,
  submitPasscode,
  type DemoEntryState,
  type LoginState,
} from "./actions";

const INITIAL: LoginState = { status: "idle" };
const DEMO_INITIAL: DemoEntryState = { status: "idle" };

interface LoginFormProps {
  devHint: string | null;
  /** Halaman tujuan setelah login, dari `?next=` yang dipasang proxy. */
  nextPath?: string;
  /** Jalur masuk demo aktif: tombol satu klik menjadi jalur utama. */
  demoEnabled?: boolean;
}

export function LoginForm({ devHint, nextPath, demoEnabled = false }: LoginFormProps) {
  // Deadline cooldown disimpan sebagai waktu absolut, bukan hitungan detik
  // yang dikurangi: hitungan bisa meleset kalau tab tidak aktif.
  const [cooldownUntil, setCooldownUntil] = useState(0);
  const [now, setNow] = useState(() => Date.now());
  const [showPasscode, setShowPasscode] = useState(false);
  // Hanya dipakai saat jalur demo aktif. Saat jalur demo mati, form passcode
  // adalah satu-satunya jalan masuk, jadi ia dirender langsung.
  const [passcodeOpen, setPasscodeOpen] = useState(false);
  const passcodePanelId = useId();

  const [state, formAction, pending] = useActionState(
    async (prev: LoginState, formData: FormData) => {
      const result = await submitPasscode(prev, formData);
      if (result.status === "rate_limited" && result.retryAfterSeconds) {
        setCooldownUntil(Date.now() + result.retryAfterSeconds * 1000);
        setNow(Date.now());
      }
      return result;
    },
    INITIAL,
  );

  // Action demo hanya menyetel cookie gerbang lalu mengalihkan. Kalau sakelar
  // produk mati, ia mengembalikan pesan dan tidak menyentuh cookie sama sekali.
  const [demoState, demoAction, demoPending] = useActionState(enterDemo, DEMO_INITIAL);

  // Denyut waktu hanya ditulis dari dalam callback interval, bukan langsung
  // di body effect, supaya tidak memicu render berantai.
  useEffect(() => {
    if (cooldownUntil === 0) return;
    const interval = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(interval);
  }, [cooldownUntil]);

  const secondsLeft = Math.max(0, Math.ceil((cooldownUntil - now) / 1000));
  const locked = secondsLeft > 0;
  const errorMessage = state.status === "rate_limited"
    ? `Terlalu banyak percobaan. Coba lagi dalam ${secondsLeft} detik.`
    : state.message;

  const renderPasscodeForm = (autoFocusInput: boolean) => (
    <form action={formAction} className="flex flex-col gap-5" noValidate>
      {nextPath ? <input type="hidden" name="next" value={nextPath} /> : null}
      <div className="flex flex-col gap-1.5">
        <Label htmlFor="passcode" className="text-[13px] font-medium">
          Passcode akses
        </Label>
        <div className="relative">
          <Input
            id="passcode"
            name="passcode"
            type={showPasscode ? "text" : "password"}
            autoComplete="current-password"
            autoFocus={autoFocusInput}
            required
            disabled={pending || locked}
            placeholder="Masukkan passcode"
            aria-invalid={state.status === "error"}
            aria-describedby="passcode-feedback"
            className="pr-10 font-mono tracking-wide"
          />
          <button
            type="button"
            onClick={() => setShowPasscode((value) => !value)}
            disabled={pending || locked}
            className="absolute inset-y-0 right-0 flex w-10 items-center justify-center rounded-r-lg text-muted-foreground transition-colors hover:text-foreground disabled:pointer-events-none disabled:opacity-50"
            aria-label={showPasscode ? "Sembunyikan passcode" : "Tampilkan passcode"}
          >
            {showPasscode ? <EyeOff className="size-4" /> : <Eye className="size-4" />}
          </button>
        </div>
      </div>

      {/* Error inline, bukan Alert besar: satu field, satu pesan. */}
      <p
        id="passcode-feedback"
        role={state.status === "idle" ? undefined : "alert"}
        className="min-h-5 text-[13px] leading-5"
        data-state={state.status}
      >
        {errorMessage ? (
          <span className={locked ? "text-warning-ink" : "text-destructive"}>
            {errorMessage}
          </span>
        ) : devHint ? (
          <span className="text-muted-foreground">
            Mode pengembangan. Passcode: <code className="font-mono">{devHint}</code>
          </span>
        ) : null}
      </p>

      <Button type="submit" size="lg" disabled={pending || locked} className="w-full gap-2">
        {pending ? (
          <>
            <Loader2 className="size-4 animate-spin" aria-hidden />
            Memverifikasi...
          </>
        ) : (
          <>
            <LogIn className="size-4" aria-hidden />
            Masuk
          </>
        )}
      </Button>
    </form>
  );

  if (!demoEnabled) {
    return renderPasscodeForm(true);
  }

  return (
    <div className="flex flex-col gap-5">
      {/* Form demo dan form passcode adalah dua form bersaudara. HTML tidak
          mengizinkan form bersarang, dan passcode hanyalah jalur sekunder. */}
      <form action={demoAction} className="flex flex-col gap-3">
        {nextPath ? <input type="hidden" name="next" value={nextPath} /> : null}
        <Button type="submit" size="lg" disabled={demoPending} className="w-full gap-2">
          {demoPending ? (
            <>
              <Loader2 className="size-4 animate-spin" aria-hidden />
              Menyiapkan demo...
            </>
          ) : (
            <>
              <LogIn className="size-4" aria-hidden />
              Masuk demo
            </>
          )}
        </Button>
      </form>

      {demoState.status === "error" && demoState.message ? (
        <p role="alert" className="-mt-2 text-[13px] leading-5 text-destructive">
          {demoState.message}
        </p>
      ) : null}

      <div className="flex flex-col items-center">
        <Button
          type="button"
          variant="ghost"
          size="lg"
          className="min-h-11 w-full text-[13px] font-normal text-muted-foreground"
          aria-expanded={passcodeOpen}
          aria-controls={passcodePanelId}
          onClick={() => setPasscodeOpen((open) => !open)}
        >
          Punya passcode?
        </Button>

        {/* Panel tetap ada agar `aria-controls` menunjuk elemen nyata, tetapi
            form-nya hanya dibuat saat terbuka: input passcode tidak ikut
            ter-fokus saat pengguna datang untuk menekan tombol demo. */}
        <div
          id={passcodePanelId}
          className={passcodeOpen ? "w-full pt-4" : "hidden"}
        >
          {passcodeOpen ? renderPasscodeForm(true) : null}
        </div>
      </div>
    </div>
  );
}

export function LoginAside() {
  return (
    <aside className="hidden flex-col justify-between border-l border-border bg-card p-8 lg:flex lg:w-80">
      <Logo size={40} markOnly />
      <div className="flex flex-col gap-2">
        <p className="eyebrow">Tentang akses ini</p>
        <p className="text-[13px] leading-relaxed text-muted-foreground">
          Ini demo portofolio dengan satu passcode tunggal, bukan sistem akun.
          Backend FastAPI tetap memverifikasi passcode dan membatasi percobaan
          dari sisi server.
        </p>
      </div>
    </aside>
  );
}