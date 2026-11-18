import type { MetadataRoute } from "next";

/**
 * robots.txt: halaman boleh dirayapi.
 *
 * Sitemap sengaja tidak ditautkan: route `/sitemap.xml` tidak ada di aplikasi
 * ini, dan menautkan URL yang 404 justru menyesatkan perayap.
 */
export default function robots(): MetadataRoute.Robots {
  return {
    rules: { userAgent: "*", allow: "/" },
  };
}
