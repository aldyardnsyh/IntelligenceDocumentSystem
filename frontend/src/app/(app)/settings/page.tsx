import type { Metadata } from "next";
import { SettingsView } from "@/components/settings/settings-view";

export const metadata: Metadata = {
  title: "Pengaturan",
  description: "Parameter retrieval, tampilan, dan reset sesi.",
};

export default function SettingsPage() {
  return (
    <div className="mx-auto flex w-full max-w-[1200px] flex-1 flex-col px-4 py-8 sm:px-6">
      <SettingsView />
    </div>
  );
}
