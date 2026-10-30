"use client";

import { clsx } from "clsx";
import { TrendingDown, TrendingUp, Minus } from "lucide-react";

export interface BullBaseBearScenario {
  key: string;
  label_ru: string;
  probability: number;
  expected_return: number | null;
  narrative: string;
}

function pctProb(value: number): string {
  return `${(value * 100).toFixed(0)}%`;
}

function pctRet(value: number | null): string {
  if (value == null) return "—";
  const sign = value >= 0 ? "+" : "";
  return `${sign}${(value * 100).toFixed(2)}%`;
}

const ICONS = {
  bull: TrendingUp,
  base: Minus,
  bear: TrendingDown,
};

const COLORS = {
  bull: "text-terminal-up border-terminal-up/30",
  base: "text-terminal-accent border-terminal-accent/30",
  bear: "text-terminal-down border-terminal-down/30",
};

export function BullBaseBearPanel({ scenarios }: { scenarios: BullBaseBearScenario[] }) {
  if (!scenarios.length) return null;

  return (
    <section className="cockpit-panel p-4 space-y-3">
      <h2 className="text-sm font-bold uppercase tracking-wide text-terminal-accent">
        Рост / база / падение
      </h2>
      <p className="text-xs text-qa-muted">
        Три сценария: медианный базовый случай, бычий и медвежий — привязаны к ensemble и
        stress-test.
      </p>
      <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
        {scenarios.map((s) => {
          const Icon = ICONS[s.key as keyof typeof ICONS] ?? Minus;
          const color = COLORS[s.key as keyof typeof COLORS] ?? COLORS.base;
          return (
            <div
              key={s.key}
              className={clsx(
                "rounded-lg border bg-cockpit-panel-raised p-3 space-y-2",
                color.split(" ")[1],
              )}
            >
              <div className="flex items-center justify-between">
                <div className={clsx("flex items-center gap-2", color.split(" ")[0])}>
                  <Icon size={16} />
                  <span className="text-sm font-semibold">{s.label_ru}</span>
                </div>
                <span className="font-mono text-sm text-white">{pctProb(s.probability)}</span>
              </div>
              <p className="text-lg font-mono tabular-nums text-white">{pctRet(s.expected_return)}</p>
              <p className="text-xs text-qa-muted leading-relaxed">{s.narrative}</p>
            </div>
          );
        })}
      </div>
    </section>
  );
}
