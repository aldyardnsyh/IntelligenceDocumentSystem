import type { Metadata } from "next";
import { Inter, JetBrains_Mono } from "next/font/google";
import { Toaster } from "@/components/ui/sonner";
import { Providers } from "./providers";
import "./globals.css";

/**
 * Inter dipakai karena produk ini membaca teks panjang (isi dokumen, kutipan
 * chunk, log query) di layar 14px. Metrik hurufnya netral dan legibilitasnya
 * konsisten lintas platform, berbeda dari Geist yang lebih cocok untuk UI
 * konsol. JetBrains Mono disimpan khusus untuk data yang dihasilkan mesin
 * (id chunk, id dokumen, skor) supaya kolom angka sejajar dan terbaca sebagai
 * data, bukan prosa.
 */
const inter = Inter({
  subsets: ["latin"],
  variable: "--font-inter",
  display: "swap",
});

const jetbrains = JetBrains_Mono({
  subsets: ["latin"],
  variable: "--font-jetbrains",
  weight: ["400", "500"],
  display: "swap",
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
    <html lang="id" className={`${inter.variable} ${jetbrains.variable} h-full`}>
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
