import { Suspense } from "react";
import type { Metadata } from "next";
import { ChatShell } from "@/components/chat/chat-shell";

export const metadata: Metadata = {
  title: "Chat",
  description: "Tanya dokumen Anda dan baca jawaban beserta sumbernya.",
};

/**
 * Halaman ini membaca `searchParams` (`?doc=<id>`), jadi dirender per
 * permintaan.
 *
 * Penanda ini menyatakan maksud kode, bukan tambalan untuk kegagalan build:
 * halaman yang isinya bergantung pada `?doc=` tidak bisa dibekukan saat
 * build, karena nilai itu belum ada pada waktu itu.
 */
export const dynamic = "force-dynamic";

export default async function ChatPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  // `?doc=<id>` memulai chat yang hanya mencari di dokumen itu. Dipakai
  // tombol "Tanya dokumen ini" di halaman dokumen, dan bertahan sampai sesi
  // dibuat, setelah itu scope disimpan di sesi, bukan di URL.
  const params = await searchParams;
  const raw = params.doc;
  const documentId = typeof raw === "string" && raw.length > 0 ? raw : null;

  return (
    <Suspense fallback={<div className="flex-1" />}>
      <ChatShell documentId={documentId} />
    </Suspense>
  );
}
