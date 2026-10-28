import type { MetadataRoute } from "next";
import { isDemoEntryEnabled } from "@/lib/demo/profile";

/**
 * robots.txt dibangkitkan dari profil build, bukan ditulis statis.
 *
 * Profil demo publik (fixture in-browser dengan `NEXT_PUBLIC_DEMO_ENTRY` aktif)
 * tidak boleh masuk indeks mesin pencari: isinya data contoh, bukan dokumen
 * milik pengunjung, dan URL-nya tidak stabil antar deploy. Selain profil itu —
 * termasuk build fixture untuk pengembangan lokal — halaman boleh dirayapi.
 *
 * Sitemap sengaja tidak ditautkan: route `/sitemap.xml` tidak ada di aplikasi
 * ini, dan menautkan URL yang 404 justru menyesatkan perayap.
 */
export default function robots(): MetadataRoute.Robots {
  if (isDemoEntryEnabled) {
    return {
      rules: { userAgent: "*", disallow: "/" },
    };
  }

  return {
    rules: { userAgent: "*", allow: "/" },
  };
}