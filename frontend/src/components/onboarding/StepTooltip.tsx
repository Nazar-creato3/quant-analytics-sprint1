"use client";

import { useEffect, useLayoutEffect, useRef, useState } from "react";
import type { TourStep } from "@/lib/onboarding/tourCatalog";

type Pos = { top: number; left: number };

function placeCard(targetId: string | undefined, width: number, height: number): Pos {
  const vw = window.innerWidth;
  const vh = window.innerHeight;
  const margin = 16;
  if (!targetId) {
    return { top: Math.max(margin, (vh - height) / 2), left: Math.max(margin, (vw - width) / 2) };
  }
  const el = document.querySelector<HTMLElement>(`[data-tour="${targetId}"]`);
  if (!el) {
    return { top: Math.max(margin, vh - height - 28), left: Math.max(margin, vw - width - 28) };
  }
  const r = el.getBoundingClientRect();
  let top = r.bottom + 12;
  let left = r.left;
  if (top + height > vh - margin) top = Math.max(margin, r.top - height - 12);
  if (left + width > vw - margin) left = Math.max(margin, vw - width - margin);
  if (left < margin) left = margin;
  if (top < margin) top = margin;
  return { top, left };
}

export function StepTooltip({
  step,
  index,
  total,
  onNext,
  onBack,
  onDismiss,
}: {
  step: TourStep;
  index: number;
  total: number;
  onNext: () => void;
  onBack: () => void;
  onDismiss: () => void;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const [pos, setPos] = useState<Pos>({ top: 80, left: 24 });

  useLayoutEffect(() => {
    const node = ref.current;
    if (!node) return;
    const { width, height } = node.getBoundingClientRect();
    setPos(placeCard(step.target, width, height));
  }, [step.id, step.target]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onDismiss();
      if (e.key === "ArrowRight") onNext();
      if (e.key === "ArrowLeft") onBack();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onDismiss, onNext, onBack]);

  const last = index >= total - 1;

  return (
    <div
      ref={ref}
      role="dialog"
      aria-modal="false"
      aria-labelledby="onboarding-title"
      className="fixed z-[70] w-[min(22rem,calc(100vw-2rem))] rounded-xl border border-cockpit-border bg-cockpit-surface shadow-xl shadow-black/40"
      style={{ top: pos.top, left: pos.left }}
    >
      <div className="px-4 pt-3 pb-1 flex items-center justify-between gap-3">
        <p className="text-[10px] uppercase tracking-wider text-qa-muted">
          Экскурс · {index + 1} из {total}
        </p>
        <button
          type="button"
          onClick={onDismiss}
          className="text-[11px] text-qa-muted hover:text-qa-text"
        >
          Закрыть
        </button>
      </div>
      <div className="h-0.5 mx-4 rounded-full bg-cockpit-border overflow-hidden">
        <div
          className="h-full bg-terminal-accent/80"
          style={{ width: `${((index + 1) / total) * 100}%` }}
        />
      </div>
      <div className="px-4 py-3 space-y-2">
        <h2 id="onboarding-title" className="text-sm font-medium text-qa-text">
          {step.title}
        </h2>
        <p className="text-[13px] leading-relaxed text-qa-muted">{step.body}</p>
        {step.hint && (
          <p className="text-[11px] leading-relaxed text-qa-muted/80 border-l-2 border-terminal-accent/40 pl-2">
            {step.hint}
          </p>
        )}
      </div>
      <div className="px-4 pb-3 flex items-center justify-between gap-2">
        <button
          type="button"
          onClick={onBack}
          disabled={index === 0}
          className="text-[12px] text-qa-muted hover:text-qa-text disabled:opacity-30"
        >
          Назад
        </button>
        <button
          type="button"
          onClick={onNext}
          className="px-3 py-1.5 rounded-md text-[12px] bg-terminal-accent/15 text-terminal-accent border border-terminal-accent/40 hover:bg-terminal-accent/25"
        >
          {last ? "Готово" : "Дальше"}
        </button>
      </div>
    </div>
  );
}
