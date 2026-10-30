import type { Metadata } from "next";
import type { ReactNode } from "react";
import { SITE_ORIGIN } from "@/lib/public-site";

export const metadata: Metadata = {
  metadataBase: new URL(SITE_ORIGIN),
  title: "Методика — Quant Analytics",
  description: "Публичная методика. Незаполненные тексты не опубликованы.",
  robots: { index: true, follow: true },
  openGraph: {
    title: "Методика — Quant Analytics",
    description: "Публичная методика. Незаполненные тексты не опубликованы.",
    url: `${SITE_ORIGIN}/methodology`,
    type: "website",
  },
};

export default function MethodologyLayout({ children }: { children: ReactNode }) {
  return children;
}
