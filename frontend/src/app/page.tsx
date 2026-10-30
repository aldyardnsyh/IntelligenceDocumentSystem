import type { Metadata } from "next";
import { ArrowRight, FileUp, MessageSquareText, Quote, ShieldCheck, Upload } from "lucide-react";
import { Logo } from "@/components/brand/logo";
import { LinkButton } from "@/components/common/link-button";
import { SiteFooter } from "@/components/layout/site-footer";

export const metadata: Metadata = {
  title: "Tanya Dokumen Anda, Jawabannya Menyertakan Sumbernya",
  description:
    "Unggah PDF, TXT, atau Markdown, ajukan pertanyaan dalam bahasa sehari-hari, dan telusuri setiap jawaban sampai ke sumbernya.",
};

const STEPS = [
  {
    Icon: FileUp,
    title: "Unggah dokumen",
    body: "PDF, TXT, atau Markdown sampai 10 MB per berkas. Isi teks dipecah menjadi chunk dan diindeks otomatis.",
  },
  {
    Icon: MessageSquareText,
    title: "Ajukan pertanyaan",
    body: "Gunakan bahasa sehari-hari. Pertanyaan lanjutan tetap memakai konteks percakapan sebelumnya.",
  },
  {
    Icon: Quote,
    title: "Baca jawaban beserta sumbernya",
    body: "Setiap jawaban menyertakan dokumen, nomor halaman atau chunk, dan cuplikan teks yang dipakai.",
  },
] as const;

export default function PublicLandingPage() {
  return (
    <div className="flex min-h-dvh flex-col">
      <header className="border-b border-border bg-card">
        <div className="mx-auto flex h-14 w-full max-w-[1200px] items-center gap-4 px-4 sm:px-6">
          <span className="flex items-center gap-2.5">
            <Logo size={28} />
            <span className="text-[14px] font-semibold">Intelligent Document Assistant</span>
          </span>
          <nav aria-label="Navigasi landing" className="ml-auto flex items-center gap-2">
            <LinkButton variant="ghost" href="/login">
              Masuk
            </LinkButton>
            <LinkButton href="/login?next=/chat">
              Coba Demo
              <ArrowRight className="size-4" aria-hidden />
            </LinkButton>
          </nav>
        </div>
      </header>

      <main className="mx-auto w-full max-w-[1200px] flex-1 px-4 sm:px-6">
        <section className="flex flex-col items-center gap-6 py-16 text-center sm:py-24">
          <Logo size={72} />
          <div className="flex max-w-2xl flex-col gap-3">
            <p className="eyebrow">Asisten Dokumen Cerdas</p>
            <h1 className="text-4xl font-semibold tracking-tight text-balance sm:text-5xl">
              Tanyakan isi dokumen Anda, jawabannya menyertakan sumbernya.
            </h1>
            <p className="text-[15px] leading-relaxed text-muted-foreground text-pretty sm:text-base">
              Unggah PDF, TXT, atau Markdown, ajukan pertanyaan dengan bahasa
              sehari-hari, dan telusuri setiap jawaban sampai ke halaman atau
              chunk aslinya. Kalau informasinya memang tidak ada di dokumen,
              sistem mengatakannya terbuka, bukan mengarang.
            </p>
          </div>

          <div className="flex flex-col gap-2 sm:flex-row">
            <LinkButton size="lg" className="gap-2" href="/login?next=/chat">
              <Upload className="size-4" aria-hidden />
              Coba Demo
            </LinkButton>
            <LinkButton size="lg" variant="outline" className="gap-2" href="#cara-kerja">
              Lihat cara kerja
              <ArrowRight className="size-4" aria-hidden />
            </LinkButton>
          </div>

          <p className="max-w-md text-[12px] leading-relaxed text-muted-foreground">
            Demo portofolio dengan satu passcode akses. Isi dokumen Anda hanya
            dipakai selama sesi demo berjalan.
          </p>
        </section>

        <section className="border-t border-border py-14">
          <div className="mb-8 max-w-xl">
            <p className="eyebrow">Kenapa bisa dipercaya</p>
            <h2 className="mt-2 text-2xl font-semibold tracking-tight">
              Menolak mengarang adalah fiturnya
            </h2>
          </div>
          <ul className="grid grid-cols-1 gap-x-8 gap-y-6 md:grid-cols-3">
            <li className="flex flex-col gap-3 border-t border-border pt-4">
              <div className="flex items-center gap-2.5">
                <ShieldCheck className="size-4 text-primary" aria-hidden />
                <h3 className="text-[15px] font-semibold">Menolak mengarang</h3>
              </div>
              <p className="text-[13px] leading-relaxed text-muted-foreground">
                Kalau tidak ada potongan dokumen yang cukup mirip, jawabannya
                terus terang tidak ditemukan, bukan karangan berbalut sitasi.
              </p>
            </li>
            <li className="flex flex-col gap-3 border-t border-border pt-4">
              <div className="flex items-center gap-2.5">
                <Quote className="size-4 text-primary" aria-hidden />
                <h3 className="text-[15px] font-semibold">Sitasi yang bisa diklik</h3>
              </div>
              <p className="text-[13px] leading-relaxed text-muted-foreground">
                Tiap jawaban mencantumkan nama berkas, halaman atau chunk, dan
                cuplikan teks, sehingga bisa diverifikasi sampai ke sumbernya.
              </p>
            </li>
            <li className="flex flex-col gap-3 border-t border-border pt-4">
              <div className="flex items-center gap-2.5">
                <MessageSquareText className="size-4 text-primary" aria-hidden />
                <h3 className="text-[15px] font-semibold">Ambang kemiripan yang jujur</h3>
              </div>
              <p className="text-[13px] leading-relaxed text-muted-foreground">
                Sumber di bawah ambang tidak dipaksakan jadi jawaban. Ketatnya
                bisa diatur sendiri di halaman pengaturan.
              </p>
            </li>
          </ul>
        </section>

        <section id="cara-kerja" className="scroll-mt-16 border-t border-border py-14">
          <div className="mb-8 max-w-xl">
            <p className="eyebrow">Cara kerja</p>
            <h2 className="mt-2 text-2xl font-semibold tracking-tight">
              Dari berkas menjadi jawaban bersumber
            </h2>
          </div>
          <ol className="grid grid-cols-1 gap-x-8 gap-y-6 md:grid-cols-3">
            {STEPS.map(({ Icon, title, body }, index) => (
              <li key={title} className="flex flex-col gap-3 border-t border-border pt-4">
                <div className="flex items-center gap-2.5">
                  <span className="font-mono text-[12px] text-muted-foreground tnum">
                    0{index + 1}
                  </span>
                  <Icon className="size-4 text-primary" aria-hidden />
                  <h3 className="text-[15px] font-semibold">{title}</h3>
                </div>
                <p className="text-[13px] leading-relaxed text-muted-foreground">{body}</p>
              </li>
            ))}
          </ol>
        </section>

        <section className="border-t border-border py-14 text-center">
          <h2 className="text-2xl font-semibold tracking-tight">
            Siap mencoba dengan dokumen Anda?
          </h2>
          <p className="mx-auto mt-2 max-w-md text-[14px] leading-relaxed text-muted-foreground">
            Masuk dengan passcode demo, unggah satu berkas, dan ajukan
            pertanyaan pertama.
          </p>
          <div className="mt-6 flex justify-center">
            <LinkButton size="lg" className="gap-2" href="/login?next=/chat">
              Masuk ke Demo
              <ArrowRight className="size-4" aria-hidden />
            </LinkButton>
          </div>
        </section>
      </main>

      <SiteFooter />
    </div>
  );
}
