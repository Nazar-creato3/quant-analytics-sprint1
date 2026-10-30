"use client";

import { useEffect, useState } from "react";

/** True when the browser tab is visible (Page Visibility API). */
export function useDocumentVisibility(): boolean {
  const [visible, setVisible] = useState(true);

  useEffect(() => {
    if (typeof document === "undefined") return;
    const update = () => setVisible(document.visibilityState === "visible");
    update();
    document.addEventListener("visibilitychange", update);
    return () => document.removeEventListener("visibilitychange", update);
  }, []);

  return visible;
}

/** Poll interval when tab visible; pause when hidden. */
export function useVisiblePollInterval(intervalMs: number): number | false {
  const visible = useDocumentVisibility();
  return visible ? intervalMs : false;
}
