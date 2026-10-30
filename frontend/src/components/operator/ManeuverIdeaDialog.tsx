"use client";

import { useState } from "react";
import type { Maneuver } from "@/types";

function whyThisTrade(m: Maneuver): string | null {
  const meta = m.signal_meta;
  if (!meta || typeof meta !== "object") return null;
  const raw = meta.why_this_trade;
  return typeof raw === "string" && raw.trim() ? raw.trim() : null;
}

export function maneuverIdeaParts(m: Maneuver): { blurb: string; why: string | null } {
  const blurb =
    (m.rationale && m.rationale.trim()) ||
    `Сигнал модели (уверенность ${(m.confidence * 100).toFixed(0)}%).`;
  return { blurb, why: whyThisTrade(m) };
}

export function ManeuverIdeaButton({
  m,
  className,
}: {
  m: Maneuver;
  className?: string;
}) {
  const [open, setOpen] = useState(false);
  const { blurb, why } = maneuverIdeaParts(m);

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        className={
          className ??
          "px-2 py-1.5 text-[10px] font-semibold uppercase tracking-wide rounded-md border border-sky-500/50 text-sky-300 hover:bg-sky-500/15 shrink-0"
        }
      >
        Идея
      </button>
      {open ? (
        <div
          className="fixed inset-0 z-[80] flex items-end sm:items-center justify-center bg-black/60 p-3"
          onClick={() => setOpen(false)}
          role="presentation"
        >
          <div
            className="w-full max-w-lg max-h-[80vh] overflow-y-auto rounded-lg border border-cockpit-border bg-cockpit-panel p-4 shadow-xl"
            onClick={(e) => e.stopPropagation()}
            role="dialog"
            aria-labelledby={`idea-${m.id}`}
          >
            <div className="flex items-start justify-between gap-3 mb-3">
              <div>
                <h3 id={`idea-${m.id}`} className="text-sm font-semibold text-qa-text">
                  {m.ticker} · идея
                </h3>
                <p className="text-[10px] text-qa-muted mt-0.5">
                  уверенность {(m.confidence * 100).toFixed(0)}%
                  {m.position_size_usd > 0
                    ? ` · $${m.position_size_usd.toLocaleString("en", { maximumFractionDigits: 0 })}`
                    : ""}
                </p>
              </div>
              <button
                type="button"
                onClick={() => setOpen(false)}
                className="text-[11px] text-qa-muted hover:text-qa-text"
              >
                Закрыть
              </button>
            </div>
            {why ? (
              <section className="mb-3">
                <h4 className="text-[10px] uppercase tracking-wide text-qa-muted mb-1">
                  Почему эта идея
                </h4>
                <p className="text-xs text-qa-text/90 leading-relaxed whitespace-pre-wrap">{why}</p>
              </section>
            ) : null}
            <section>
              <h4 className="text-[10px] uppercase tracking-wide text-qa-muted mb-1">
                Сигнал на карточке
              </h4>
              <p className="text-xs text-qa-text/90 leading-relaxed whitespace-pre-wrap">{blurb}</p>
            </section>
          </div>
        </div>
      ) : null}
    </>
  );
}
