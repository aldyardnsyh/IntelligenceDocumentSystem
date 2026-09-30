/**
 * Health check untuk container dan load balancer.
 *
 * Sengaja dipisah dari halaman biasa: route ini tidak menjalankan middleware
 * proxy (dengan begitu tetap publik), tidak menyentuh API, dan tidak butuh
 * sesi. Gunanya satu: memungkinkan orkestrator memeriksa "apakah proses
 * Next masih melayani" tanpa bergantung pada apa pun yang lain.
 *
 * Route handler, bukan komponen halaman, karena tidak perlu render React
 * sama sekali.
 */

export const dynamic = "force-dynamic";

export function GET() {
  return Response.json(
    {
      status: "ok",
      service: "frontend",
      uptimeSeconds: Math.round(process.uptime()),
    },
    {
      headers: {
        // Health check tidak boleh di-cache; cache yang_hit membuat
        // orkestrator melihat instance yang sudah mati sebagai yang sehat.
        "cache-control": "no-store",
      },
    },
  );
}
