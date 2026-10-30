"use client";

import { clsx } from "clsx";
import { useLocale } from "@/contexts/LocaleContext";
import type { MarketBeatData, MarketBeatSubscore } from "@/types";

function ScoreBadge({ value, label, of10 }: { value: number; label: string; of10: string }) {
  const tone =
    value >= 8 ? "text-emerald-300 border-emerald-500/40" : value <= 3 ? "text-rose-300 border-rose-500/40" : "text-qa-text border-white/15";
  return (
    <div className={clsx("rounded-lg border px-3 py-2 min-w-[5.5rem]", tone)}>
      <div className="text-[10px] uppercase tracking-wide text-qa-muted">{label}</div>
      <div className="text-2xl font-bold font-mono leading-none mt-1">{value}</div>
      <div className="text-[10px] text-qa-muted mt-1">{of10}</div>
    </div>
  );
}

function Subscore({
  title,
  block,
  noData,
}: {
  title: string;
  block: MarketBeatSubscore | null | undefined;
  noData: string;
}) {
  if (!block?.available) {
    return (
      <div className="text-xs text-qa-muted">
        <span className="text-qa-text/80">{title}:</span> {noData}
      </div>
    );
  }
  return (
    <div className="text-xs">
      <span className="text-qa-text/80">{title}:</span>{" "}
      <span className="font-mono">{block.score}</span>
      {block.p != null ? <span className="text-qa-muted"> ({Math.round(block.p * 100)}%)</span> : null}
    </div>
  );
}

export function MarketBeatPanel({ beat }: { beat: MarketBeatData }) {
  const { t } = useLocale();
  return (
    <section className="cockpit-panel p-4 space-y-3">
      <div className="flex items-baseline justify-between gap-3">
        <h3 className="text-sm font-bold uppercase tracking-wide text-terminal-accent">
          {t("beat.title")}
        </h3>
        <span className="text-[10px] text-qa-muted font-mono">{beat.symbol}</span>
      </div>
      <p className="text-sm text-qa-text/90 leading-relaxed">{beat.explanation_ru}</p>
      <div className="flex flex-wrap gap-3">
        {/* One trained horizon: the LightGBM beat model is 20 sessions. Requests for 1, 5 and
            60 days fell back to the same model, so extra badges only repeated this number. */}
        <ScoreBadge value={beat.score_20} label={t("beat.sessions20")} of10={t("beat.of10")} />
      </div>
      <div className="grid sm:grid-cols-2 gap-2 text-xs">
        <div>
          <Subscore title={t("beat.tech")} block={beat.subscores?.technical} noData={t("beat.noData")} />
          <Subscore title={t("beat.fund")} block={beat.subscores?.fundamental} noData={t("beat.noData")} />
          <Subscore title={t("beat.news")} block={beat.subscores?.news} noData={t("beat.noData")} />
        </div>
        <div className="space-y-1">
          <div>
            <span className="text-qa-muted">{t("beat.timing")}:</span> {beat.timing_ru}
          </div>
          <div>
            <span className="text-qa-muted">{t("beat.who")}:</span> {beat.benchmark_hint}
          </div>
          {beat.live_n > 0 && beat.live_accuracy != null ? (
            <div>
              <span className="text-qa-muted">{t("beat.track")}:</span>{" "}
              {Math.round(beat.live_accuracy * 100)}% / {beat.live_n}
            </div>
          ) : null}
          <div className="text-qa-muted">{t("beat.sizeNote")}</div>
        </div>
      </div>
    </section>
  );
}
