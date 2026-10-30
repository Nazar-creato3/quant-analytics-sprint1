"use client";

import { ArrowLeft } from "lucide-react";

/** «Назад» that returns to the previous screen of the app, or to the home page if there is none. */
export function BackButton({ fallback = "/", className = "" }: { fallback?: string; className?: string }) {
  return (
    <button
      type="button"
      data-testid="back-button"
      onClick={() => {
        const sameOrigin = document.referrer.startsWith(window.location.origin);
        if (sameOrigin && window.history.length > 1) window.history.back();
        else window.location.assign(fallback);
      }}
      className={`inline-flex items-center gap-1.5 text-xs text-qa-muted hover:text-qa-text transition-colors ${className}`}
    >
      <ArrowLeft size={14} aria-hidden />
      Назад
    </button>
  );
}
