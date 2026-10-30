import type { Metadata } from "next";
import type { ReactNode } from "react";
import { SITE_ORIGIN } from "@/lib/public-site";

export const metadata: Metadata = {
  metadataBase: new URL(SITE_ORIGIN),
  robots: { index: true, follow: true },
};

export default function LegalLayout({ children }: { children: ReactNode }) {
  return children;
}
