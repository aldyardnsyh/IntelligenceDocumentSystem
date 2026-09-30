import { SiteFooter } from "@/components/layout/site-footer";
import { SiteHeader } from "@/components/layout/site-header";

/**
 * Layout untuk semua halaman yang butuh sesi. Rute di dalam grup ini sudah
 * dijaga proxy.ts, jadi tidak perlu cek passcode lagi di sini.
 */
export default function AppShellLayout({ children }: LayoutProps<"/">) {
  return (
    <div className="flex min-h-dvh flex-col">
      <SiteHeader />
      <div className="flex flex-1 flex-col">{children}</div>
      <SiteFooter />
    </div>
  );
}
