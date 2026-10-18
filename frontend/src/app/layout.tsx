import type { Metadata } from "next";
import localFont from "next/font/local";
import { Toaster } from "@/components/ui/sonner";
import { Providers } from "./providers";
import "./globals.css";

/**
 * Plus Jakarta Sans dipakai karena produk ini membaca teks panjang (isi
 * dokumen, kutipan chunk, log query) di layar 14px. Hurufnya punya tinggi x
 * yang besar dan terminal yang terbuka, sehingga tetap terbaca di ukuran
 * kecil tanpa perlu menebalkan seluruh antarmuka. JetBrains Mono disimpan
 * khusus untuk data yang dihasilkan mesin (id chunk, id dokumen, skor) supaya
 * kolom angka sejajar dan terbaca sebagai data, bukan prosa.
 *
 * Berkasnya disimpan di `./fonts` dan dimuat dengan `next/font/local`, bukan
 * `next/font/google`. Alasannya bukan selera: `next/font/google` mengunduh
 * berkas dari fonts.googleapis.com pada saat build. Build yang bergantung pada
 * internet akan gagal di lingkungan yang membatasi akses keluar, dan kegagalan
 * itu muncul sebagai pesan yang menyesatkan, "next/font/google queries have
 * exactly one entry", bukan sebagai error jaringan. Dengan berkas lokal, build
 * selalu bisa dijalankan tanpa jaringan, dan versi font yang terpasang tidak
 * berubah diam-diam saat Google memperbarui berkasnya.
 *
 * Kedua berkas adalah font variabel subset latin, jadi tidak perlu menyebut
 * daftar weight: satu berkas sudah mencakup seluruh rentang berat. Untuk Plus
 * Jakarta Sans rentangnya 200 sampai 800, dan JetBrains Mono 100 sampai 800.
 */
const jakarta = localFont({
  src: "./fonts/plus-jakarta-sans-latin.woff2",
  variable: "--font-jakarta",
  display: "swap",
  fallback: ["system-ui", "arial"],
});

const jetbrains = localFont({
  src: "./fonts/jetbrains-mono-latin.woff2",
  variable: "--font-jetbrains",
  display: "swap",
  fallback: ["ui-monospace", "monospace"],
});

export const metadata: Metadata = {
  title: {
    default: "Intelligent Document Assistant",
    template: "%s - Intelligent Document Assistant",
  },
  description:
    "Tanya dokumen Anda dalam bahasa natural dan dapatkan jawaban yang menyertakan sumbernya.",
  robots: { index: false, follow: false },
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="id" className={`${jakarta.variable} ${jetbrains.variable} h-full`}>
      <body className="flex min-h-full flex-col antialiased">
        <Providers>
          {children}
          <Toaster
            position="bottom-right"
            theme="light"
            closeButton
            richColors={false}
          />
        </Providers>
      </body>
    </html>
  );
}
