import { Suspense } from "react";
import type { Metadata } from "next";
import { DocumentDetailView } from "@/components/documents/document-detail-view";
import { ChunkListSkeleton } from "@/components/common/skeletons";

export const metadata: Metadata = {
  title: "Detail Dokumen",
  description: "Verifikasi metadata dan daftar chunk hasil ingestion.",
};

export default async function DocumentDetailPage({ params }: PageProps<"/documents/[id]">) {
  const { id } = await params;

  return (
    <Suspense fallback={<ChunkListSkeleton />}>
      <DocumentDetailView key={id} />
    </Suspense>
  );
}
