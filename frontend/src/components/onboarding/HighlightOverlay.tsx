"use client";

import { useEffect, useState } from "react";

type Rect = { top: number; left: number; width: number; height: number };

function readTargetRect(tourId: string): Rect | null {
  const el = document.querySelector<HTMLElement>(`[data-tour="${tourId}"]`);
  if (!el) return null;
  const r = el.getBoundingClientRect();
  if (r.width < 2 || r.height < 2) return null;
  const pad = 6;
  return {
    top: Math.max(8, r.top - pad),
    left: Math.max(8, r.left - pad),
    width: r.width + pad * 2,
    height: r.height + pad * 2,
  };
}

export function HighlightOverlay({ target }: { target?: string }) {
  const [rect, setRect] = useState<Rect | null>(null);

  useEffect(() => {
    if (!target) {
      setRect(null);
      return;
    }
    const update = () => setRect(readTargetRect(target));
    update();
    const ro = new ResizeObserver(update);
    ro.observe(document.documentElement);
    window.addEventListener("resize", update);
    window.addEventListener("scroll", update, true);
    const tick = window.setInterval(update, 400);
    return () => {
      ro.disconnect();
      window.removeEventListener("resize", update);
      window.removeEventListener("scroll", update, true);
      window.clearInterval(tick);
    };
  }, [target]);

  if (!rect) return null;

  return (
    <div
      aria-hidden
      className="pointer-events-none fixed z-[60] rounded-lg border border-terminal-accent/70"
      style={{
        top: rect.top,
        left: rect.left,
        width: rect.width,
        height: rect.height,
        boxShadow: "0 0 0 9999px rgba(8, 12, 18, 0.45), 0 0 0 1px rgba(56, 189, 248, 0.25)",
      }}
    />
  );
}
