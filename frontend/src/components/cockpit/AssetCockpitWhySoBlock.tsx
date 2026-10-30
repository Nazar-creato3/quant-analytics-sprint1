"use client";

import { format, parseISO } from "date-fns";
import type { AssetCockpitData } from "@/types";
import { CockpitPanelHeader } from "@/components/operator/CockpitPanelHeader";

interface AssetCockpitWhySoBlockProps {
  whySo: NonNullable<AssetCockpitData["why_so"]>;
}

function ExplanationBlock({ title, text }: { title: string; text: string }) {
  return (
    <div className="border-b border-cockpit-border/60 last:border-0 pb-2 last:pb-0">
      <div className="text-[10px] uppercase tracking-wide text-qa-muted mb-1">{title}</div>
      <p className="text-[11px] leading-relaxed text-qa-text">{text}</p>
    </div>
  );
}

export function AssetCockpitWhySoBlock({ whySo }: AssetCockpitWhySoBlockProps) {
  return (
    <div className="cockpit-panel">
      <CockpitPanelHeader title="Почему так" subtitle="Explainability layer" />
      <div className="p-3 space-y-3">
        <p className="text-[11px] leading-relaxed text-qa-text">{whySo.headline}</p>

        {whySo.regime_explanation && (
          <ExplanationBlock title="Regime" text={whySo.regime_explanation} />
        )}
        {whySo.factor_explanation && (
          <ExplanationBlock title="Factor model" text={whySo.factor_explanation} />
        )}
        {whySo.forecast_explanation && (
          <ExplanationBlock title="Forecast" text={whySo.forecast_explanation} />
        )}
        {whySo.risk_explanation && (
          <ExplanationBlock title="Risk" text={whySo.risk_explanation} />
        )}

        {whySo.recent_decisions.length > 0 && (
          <div>
            <div className="text-[10px] uppercase tracking-wide text-qa-muted mb-1">
              Последние решения
            </div>
            <div className="space-y-1 max-h-40 overflow-y-auto">
              {whySo.recent_decisions.map((item, index) => (
                <div key={`${item.decision_type}-${index}`} className="cockpit-feed-item text-[10px]">
                  <div className="flex items-center justify-between gap-2 text-qa-muted">
                    <span className="uppercase">{item.decision_type}</span>
                    {item.timestamp && (
                      <span className="tabular-nums">
                        {format(parseISO(item.timestamp), "dd MMM HH:mm")}
                      </span>
                    )}
                  </div>
                  <p className="text-qa-text mt-0.5 leading-relaxed">{item.text}</p>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
