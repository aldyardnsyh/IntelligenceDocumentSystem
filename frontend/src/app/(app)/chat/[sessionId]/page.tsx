import { Suspense } from "react";
import type { Metadata } from "next";
import { ChatShell } from "@/components/chat/chat-shell";
import { ChunkListSkeleton } from "@/components/common/skeletons";

export const metadata: Metadata = {
  title: "Percakapan",
};

export default async function ChatSessionPage({ params }: PageProps<"/chat/[sessionId]">) {
  const { sessionId } = await params;

  return (
    <Suspense fallback={<ChunkListSkeleton />}>
      <ChatShell key={sessionId} sessionId={sessionId} />
    </Suspense>
  );
}
