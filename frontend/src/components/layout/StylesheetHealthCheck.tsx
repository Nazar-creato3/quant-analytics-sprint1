"use client";

import { useEffect } from "react";
import { CHART_COLORS } from "@/lib/chartColors";

/**
 * Dev-only: warn when Tailwind/CSS did not load (unstyled page symptom).
 * Usually fixed by `npm run dev:clean` — stale Next.js on port 3000.
 */
export function StylesheetHealthCheck() {
  useEffect(() => {
    if (process.env.NODE_ENV !== "development") return;

    const timer = window.setTimeout(() => {
      const probe = document.createElement("div");
      probe.className = "hidden";
      probe.style.position = "absolute";
      probe.style.pointerEvents = "none";
      document.body.appendChild(probe);
      const cssLoaded = getComputedStyle(probe).display === "none";
      probe.remove();

      if (cssLoaded) return;

      console.warn(
        "[Quant Analytics] Stylesheets failed to load. " +
          "Run: cd frontend && npm run dev:clean",
      );

      const banner = document.createElement("div");
      banner.setAttribute("role", "alert");
      banner.style.cssText =
        `position:fixed;top:0;left:0;right:0;z-index:99999;padding:10px 16px;` +
        `background:${CHART_COLORS.alertBg};color:${CHART_COLORS.alertText};` +
        `font:13px/1.4 system-ui,sans-serif;border-bottom:1px solid ${CHART_COLORS.alertBorder};` +
        "text-align:center";
      banner.textContent =
        "CSS failed to load (unstyled page). Stop dev server and run: npm run dev:clean";
      document.body.prepend(banner);
    }, 1500);

    return () => window.clearTimeout(timer);
  }, []);

  return null;
}
