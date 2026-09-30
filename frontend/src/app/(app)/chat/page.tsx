import { Suspense } from "react";
import type { Metadata } from "next";
import { ChatShell } from "@/components/chat/chat-shell";

export const metadata: Metadata = {
  title: "Chat",
  description: "Tanya dokumen Anda dan baca jawaban beserta sumbernya.",
};

export default function ChatPage() {
  return (
    <Suspense fallback={<div className="flex-1" />}>
      <ChatShell />
    </Suspense>
  );
}
