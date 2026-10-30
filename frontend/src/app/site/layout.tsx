import type { Metadata } from "next";
import type { ReactNode } from "react";
import { SITE_ORIGIN } from "@/lib/public-site";

export const metadata: Metadata = {
  metadataBase: new URL(SITE_ORIGIN),
  title: "Quant Analytics",
  description: "Публичные страницы. Незаполненные тексты не опубликованы.",
  robots: { index: true, follow: true },
  openGraph: {
    title: "Quant Analytics",
    description: "Публичные страницы. Незаполненные тексты не опубликованы.",
    url: `${SITE_ORIGIN}/site`,
    type: "website",
  },
};

const jsonLd = {
  "@context": "https://schema.org",
  "@type": "WebSite",
  name: "Quant Analytics",
  url: `${SITE_ORIGIN}/site`,
};

export default function PublicSiteLayout({ children }: { children: ReactNode }) {
  return (
    <>
      <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: JSON.stringify(jsonLd) }} />
      {children}
    </>
  );
}
