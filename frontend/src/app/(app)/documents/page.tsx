import type { Metadata } from "next";
import { DocumentsView } from "@/components/documents/documents-view";

export const metadata: Metadata = {
  title: "Dokumen Saya",
  description: "Kelola dokumen sumber untuk retrieval.",
};

export default function DocumentsPage() {
  return <DocumentsView />;
}
