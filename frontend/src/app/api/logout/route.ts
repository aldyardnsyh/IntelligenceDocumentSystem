import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { SESSION_COOKIE } from "@/lib/auth/session";

/** Menghapus cookie sesi access gate lalu kembali ke layar login. */
export async function POST() {
  (await cookies()).delete(SESSION_COOKIE);
  redirect("/login");
}
