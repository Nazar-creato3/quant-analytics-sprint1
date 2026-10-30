import type { Metadata, Viewport } from "next";
import "./globals.css";
import { Providers } from "./providers";
import { Toaster } from "react-hot-toast";
import { CHART_COLORS } from "@/lib/chartColors";
import { MobileShell } from "@/components/mobile/MobileShell";
import { SupportLink } from "@/components/support/SupportLink";

export const metadata: Metadata = {
  title: "Quant Analytics — инвест-аналитика",
  description: "Операторская инвестиционно-аналитическая платформа Quant Analytics",
  robots: { index: false, follow: false },
  manifest: "/manifest.json",
  appleWebApp: {
    capable: true,
    statusBarStyle: "black-translucent",
    title: "Quant Analytics",
  },
  icons: {
    icon: [
      { url: "/favicon.ico", sizes: "any" },
      { url: "/icons/icon-16.png", sizes: "16x16", type: "image/png" },
      { url: "/icons/icon-32.png", sizes: "32x32", type: "image/png" },
      { url: "/icons/icon-192.png", sizes: "192x192", type: "image/png" },
      { url: "/icons/icon-512.png", sizes: "512x512", type: "image/png" },
    ],
    apple: [{ url: "/apple-touch-icon.png", sizes: "180x180", type: "image/png" }],
  },
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  themeColor: "#F5A623",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="ru" className="font-sans">
      {/* No third-party font CDN: loading from Google would send every visitor's
          IP abroad (cross-border transfer, 152-FZ art. 12). System fonts are used. */}
      <body className="bg-qa-bg text-qa-text antialiased">
        <Providers>
          <MobileShell>{children}</MobileShell>
          <SupportLink />
          <Toaster
            position="bottom-right"
            toastOptions={{
              style: {
                background: CHART_COLORS.crosshairLabel,
                color: CHART_COLORS.liveNeutral,
                border: `1px solid ${CHART_COLORS.border}`,
                fontSize: "13px",
                fontFamily: "var(--font-inter)",
              },
              success: {
                iconTheme: { primary: CHART_COLORS.success, secondary: CHART_COLORS.crosshairLabel },
                duration: 4000,
              },
              error: {
                iconTheme: { primary: CHART_COLORS.danger, secondary: CHART_COLORS.crosshairLabel },
                duration: 6000,
              },
            }}
          />
        </Providers>
      </body>
    </html>
  );
}