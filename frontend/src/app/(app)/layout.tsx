import { SiteFooter } from "@/components/layout/site-footer";
import { SiteHeader } from "@/components/layout/site-header";

/**
 * Layout untuk semua halaman yang butuh sesi. Rute di dalam grup ini sudah
 * dijaga proxy.ts, jadi tidak perlu cek passcode lagi di sini.
 */
export default function AppShellLayout({ children }: LayoutProps<"/">) {
  return (
    /*
     * `h-dvh` + `overflow-hidden` membuat kolom benar-benar setinggi viewport,
     * jadi area isi punya tinggi terbatas dan bisa menggulir sendiri. Dengan
     * `min-h-dvh` sebelumnya, kolom tumbuh mengikuti konten: daftar pesan tidak
     * pernah mendapat batas tinggi, `overflow-y-auto`-nya tidak pernah aktif,
     * dan yang menggulir justru dokumen — itulah yang menggeser seluruh halaman
     * setiap kali jawaban chat memanjang saat streaming.
     */
    <div className="flex h-dvh flex-col overflow-hidden">
      <div className="shrink-0">
        <SiteHeader />
      </div>
      <main className="flex min-h-0 flex-1 flex-col overflow-y-auto">{children}</main>
      <div className="shrink-0">
        <SiteFooter />
      </div>
    </div>
  );
}
