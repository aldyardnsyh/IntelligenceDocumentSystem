import type { Metadata } from "next";
import { ArrowRight, FileUp, MessageSquareText, Quote, Upload } from "lucide-react";
import { Logo } from "@/components/brand/logo";
import { LinkButton } from "@/components/common/link-button";
import { EmptyState } from "@/components/common/empty-state";

export const metadata: Metadata = {
  title: "Beranda",
  description: "Unggah dokumen, ajukan pertanyaan, dan baca jawaban beserta sumbernya.",
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

export default function LandingPage() {
  return (
    <div className="mx-auto w-full max-w-[1200px] px-4 sm:px-6">
      <section className="flex flex-col items-center gap-6 py-16 text-center sm:py-24">
        <Logo size={72} />

        <div className="flex max-w-2xl flex-col gap-3">
          <h1 className="text-4xl font-semibold tracking-tight text-balance sm:text-5xl">
            Intelligent Document Assistant
          </h1>
          <p className="text-[15px] leading-relaxed text-muted-foreground text-pretty sm:text-base">
            Unggah dokumen Anda, ajukan pertanyaan, dan dapatkan jawaban yang
            menyertakan sumbernya. Kalau informasinya memang tidak ada di
            dokumen, sistem mengatakannya terbuka, bukan mengarang.
          </p>
        </div>

        <div className="flex flex-col gap-2 sm:flex-row">
          <LinkButton size="lg" className="gap-2" href="/documents">
            <Upload className="size-4" aria-hidden />
            Mulai unggah dokumen
          </LinkButton>
          <LinkButton size="lg" variant="outline" className="gap-2" href="/chat">
            Buka chat
            <ArrowRight className="size-4" aria-hidden />
          </LinkButton>
        </div>

        <p className="max-w-md text-[12px] leading-relaxed text-muted-foreground">
          Demo portofolio dengan satu passcode akses. Isi dokumen Anda hanya
          dipakai selama sesi demo berjalan.
        </p>
      </section>

      {/*
        Alur kerja ditampilkan sebagai daftar bertipe border atas, bukan tiga
        kartu identik: yang penting urutan dan hierarkinya, bukan keseragaman
        visual antar kartu.
      */}
      <section className="border-t border-border py-14">
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

      <section className="border-t border-border py-14">
        {/*
          Empty state yang jujur: tanpa dokumen, chat memang tidak bisa
          dipakai, dan alasannya ditulis eksplisit.
        */}
        <EmptyState
          Icon={FileUp}
          title="Belum ada dokumen untuk ditanyai"
          description="Unggah satu dokumen PDF, TXT, atau Markdown untuk mengaktifkan chat. Tanpa dokumen, sistem tidak punya sumber untuk menjawab."
          action={
            <LinkButton className="mt-1 gap-2" href="/documents">
              <Upload className="size-4" aria-hidden />
              Unggah dokumen pertama
            </LinkButton>
          }
          className="border-solid"
        />
      </section>
    </div>
  );
}
