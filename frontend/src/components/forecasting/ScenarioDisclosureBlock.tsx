"use client";

import { clsx } from "clsx";
import { ChevronDown, Layers } from "lucide-react";
import { useState } from "react";
import type { ScenarioDisclosure } from "@/types";
import { pct } from "@/lib/forecast-hierarchy";
import { Spinner } from "@/components/ui";

interface ScenarioDisclosureBlockProps {
  disclosure: ScenarioDisclosure | null | undefined;
  isLoading?: boolean;
  symbol?: string;
  className?: string;
}

const VOL_REGIME_RU: Record<string, string> = {
  contained: "сдержанная",
  moderate: "умеренная",
  elevated: "повышенная",
};

const RISK_ACTION_RU: Record<string, string> = {
  wait: "ожидание",
  reduce_size: "снижение размера",
  hedge: "хеджирование",
  hold: "удержание",
  enter_small_size: "вход малым объёмом",
  enter_normal_size: "вход стандартным",
  avoid: "избегать",
};

const BREAKDOWN_LABELS: Record<string, string> = {
  macro_score: "макро",
  sector_score: "сектор",
  symbol_score: "инструмент",
  portfolio_score: "портфель",
};

function formatFreshness(iso: string | undefined): string | null {
  if (!iso) return null;
  return iso.slice(0, 19).replace("T", " ") + " UTC";
}

export function ScenarioDisclosureBlock({
  disclosure,
  isLoading = false,
  symbol,
  className,
}: ScenarioDisclosureBlockProps) {
  const [expanded, setExpanded] = useState(false);

  if (isLoading) {
    return (
      <section className={clsx("cockpit-panel p-4", className)}>
        <div className="flex flex-col items-center justify-center py-4 gap-2">
          <Spinner size={20} />
          <p className="text-xs text-qa-muted">Генерируем AI-анализ по сценариям…</p>
        </div>
      </section>
    );
  }

  if (!disclosure?.paragraphs?.length) {
    return (
      <section className={clsx("cockpit-panel p-4", className)}>
        <div className="flex items-center gap-2 mb-2">
          <Layers size={16} className="text-terminal-accent" />
          <h2 className="text-sm font-bold uppercase tracking-wide text-terminal-accent">
            Сценарные архетипы
          </h2>
        </div>
        <p className="text-sm text-qa-muted">
          По {symbol || "этой бумаге"} пока недостаточно истории для разбора по сценариям.
        </p>
      </section>
    );
  }

  const topLabel =
    disclosure.scenarios?.find((s) => s.archetype === disclosure.top_scenario)?.label_ru ??
    disclosure.top_scenario;

  const breakdown = disclosure.breakdown ?? {};
  const freshness = disclosure.freshness ?? {};
  const macroFreshness = freshness.global_macro as
    | { loaded_at?: string; is_stale?: boolean; stale_reason?: string }
    | undefined;
  const instrumentFreshness = freshness.instrument as string | undefined;

  const updatedAt =
    formatFreshness(macroFreshness?.loaded_at) ??
    formatFreshness(instrumentFreshness ?? undefined);

  const volLabel = disclosure.volatility_regime
    ? VOL_REGIME_RU[disclosure.volatility_regime] ?? disclosure.volatility_regime
    : null;
  const actionLabel = disclosure.risk_action
    ? RISK_ACTION_RU[disclosure.risk_action] ?? disclosure.risk_action
    : null;

  const visibleParagraphs = expanded
    ? disclosure.paragraphs
    : disclosure.paragraphs.slice(0, 3);

  return (
    <section className={clsx("cockpit-panel p-4 space-y-3", className)}>
      <div className="flex items-start justify-between gap-3 flex-wrap">
        <div className="space-y-1">
          <div className="flex items-center gap-2">
            <Layers size={16} className="text-terminal-accent shrink-0" />
            <h2 className="text-sm font-bold uppercase tracking-wide text-terminal-accent">
              Сценарные архетипы
            </h2>
            {disclosure.scope === "symbol" && symbol && (
              <span className="text-[10px] font-mono text-qa-muted">{symbol}</span>
            )}
          </div>
          {updatedAt && (
            <p className="text-[10px] text-qa-muted pl-6">
              Обновлено {updatedAt}
              {macroFreshness?.is_stale ? " · данные могут быть устаревшими" : ""}
            </p>
          )}
        </div>
        {disclosure.top_probability > 0 && (
          <span className="text-[10px] tabular-nums text-terminal-accent/90 shrink-0">
            лидер: {topLabel} · {pct(disclosure.top_probability)}
          </span>
        )}
      </div>

      {(disclosure.confidence != null || volLabel || actionLabel) && (
        <div className="flex flex-wrap gap-1.5 text-[10px] text-qa-muted">
          {disclosure.confidence != null && (
            <span title="Насколько модель доверяет прогнозу в целом — не путать с вероятностью одного сценария">
              уверенность {pct(disclosure.confidence)}
            </span>
          )}
          {volLabel && (
            <>
              <span className="text-qa-muted">·</span>
              <span>волатильность {volLabel}</span>
            </>
          )}
          {actionLabel && (
            <>
              <span className="text-qa-muted">·</span>
              <span>{actionLabel}</span>
            </>
          )}
          {disclosure.expected_move != null &&
            Math.abs(disclosure.expected_move) >= 0.002 && (
              <>
                <span className="text-qa-muted">·</span>
                <span>
                  ход {(disclosure.expected_move * 100).toFixed(1)}%
                </span>
              </>
            )}
        </div>
      )}

      <div className="space-y-3">
        {visibleParagraphs.map((paragraph, idx) => (
          <p
            key={idx}
            className="text-sm text-qa-text leading-relaxed tracking-normal"
          >
            {paragraph}
          </p>
        ))}
      </div>

      {disclosure.paragraphs.length > 3 && (
        <button
          type="button"
          onClick={() => setExpanded((v) => !v)}
          className="inline-flex items-center gap-1 text-[11px] text-terminal-accent hover:text-terminal-accent"
        >
          {expanded ? "Свернуть" : "Показать полностью"}
          <ChevronDown
            size={12}
            className={clsx("transition-transform", expanded && "rotate-180")}
          />
        </button>
      )}

      {(disclosure.scenarios?.length ?? 0) > 0 && (
        <div className="flex flex-wrap gap-1.5 pt-1">
          {(disclosure.scenarios ?? []).map((scenario) => (
            <span
              key={scenario.archetype}
              className={clsx(
                "text-[10px] px-2 py-0.5 rounded-full border tabular-nums",
                scenario.archetype === disclosure.top_scenario
                  ? "border-terminal-accent/40 text-terminal-accent/90 bg-[var(--qa-active)]"
                  : "border-cockpit-border/60 text-qa-muted bg-transparent",
              )}
            >
              {scenario.label_ru ?? scenario.archetype} · {pct(scenario.probability)}
            </span>
          ))}
        </div>
      )}

      {Object.keys(breakdown).length > 0 && (
        <div className="flex flex-wrap gap-x-3 gap-y-1 pt-1 border-t border-cockpit-border/40">
          {(["macro_score", "sector_score", "symbol_score", "portfolio_score"] as const).map(
            (key) => {
              const value = breakdown[key];
              if (value == null || value <= 0) return null;
              return (
                <span
                  key={key}
                  className="text-[9px] text-qa-muted tabular-nums"
                >
                  {BREAKDOWN_LABELS[key]} {pct(value)}
                </span>
              );
            },
          )}
        </div>
      )}
    </section>
  );
}
