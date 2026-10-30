"use client";

import { useEffect } from "react";

const SW_URL = "/sw.js?v=3";

export function PwaProvider({ children }: { children: React.ReactNode }) {
  useEffect(() => {
    if (typeof window === "undefined" || !("serviceWorker" in navigator)) return;

    void (async () => {
      try {
        const registrations = await navigator.serviceWorker.getRegistrations();
        for (const reg of registrations) {
          const scriptUrl = reg.active?.scriptURL ?? reg.waiting?.scriptURL ?? "";
          if (scriptUrl.includes("/sw.js") && !scriptUrl.includes("v=3")) {
            await reg.unregister();
          }
        }
        const reg = await navigator.serviceWorker.register(SW_URL);
        if (reg.waiting) {
          reg.waiting.postMessage({ type: "SKIP_WAITING" });
        }
      } catch {
        /* offline shell optional */
      }
    })();
  }, []);

  return <>{children}</>;
};
