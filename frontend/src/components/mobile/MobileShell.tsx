"use client";

import { PwaProvider } from "@/components/mobile/PwaProvider";
import { BottomTabBar } from "@/components/layout/BottomTabBar";
import { PwaInstallPrompt } from "@/components/mobile/PwaInstallPrompt";

export function MobileShell({ children }: { children: React.ReactNode }) {
  return (
    <PwaProvider>
      <div className="min-h-screen pb-14 md:pb-0">{children}</div>
      <BottomTabBar />
      <PwaInstallPrompt />
    </PwaProvider>
  );
}
