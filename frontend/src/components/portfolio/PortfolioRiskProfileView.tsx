"use client";

import { useQuery } from "@tanstack/react-query";
import { Shield } from "lucide-react";
import { portfolioApi } from "@/lib/api";
import { useAuth } from "@/hooks";
import type { PortfolioRiskAnalytics } from "@/types";
import { Skeleton } from "@/components/ui";
import { RiskAttributionPanel } from "@/components/portfolio/RiskAttributionPanel";
import { FactorCompositionPanel } from "@/components/portfolio/FactorCompositionPanel";
import { Block, DASH, Quiet, Stat, StatGrid, rub } from "@/components/portfolio/ui";
import type { UnifiedRiskSnapshot } from "@/lib/risk-engine";
import Link from "next/link";

function pct(value: number | null | undefined, digits = 2): string {
  if (value == null || !Number.isFinite(value)) return "—";
  return `${(value * 100).toFixed(digits)}%`;
}

function usd(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return "—";
  return value.toLocaleString("ru-RU", { maximumFractionDigits: 0 });
}

const LIGHT: Record<string, { text: string; tone: "up" | "accent" | "down" }> = {
  green: { text: "Спокойный", tone: "up" },
  yellow: { text: "Повышенный", tone: "accent" },
  red: { text: "Высокий", tone: "down" },
};

function RiskSummary({ engine }: { engine: UnifiedRiskSnapshot & Record<string, unknown> }) {
  const var95 = engine.var_95;
  if (var95 == null) return null;
  const rubVar = engine.rubles_var_95;
  const nav = rubVar != null && var95 ? rubVar / var95 : null;
  const es = engine.es_975;
  const rawVol = engine.volatility as number | null | undefined;
  // The engine reports daily volatility; people think in a year.
  const vol = rawVol == null ? null : rawVol < 0.1 ? rawVol * Math.sqrt(252) : rawVol;
  const beta = engine.beta as number | null | undefined;
  const dd = engine.max_drawdown as number | null | undefined;
  const light = LIGHT[String(engine.traffic_light)];
  return (
    <Block
      title="Сколько можно потерять"
      hint="Оценка по колебаниям ваших бумаг за последний год. Плохой день — такой, какой случается примерно раз в месяц; очень плохой — раз в полгода."
      method="/methodology"
      testId="risk-summary"
    >
      <StatGrid>
        <Stat label="Уровень риска" value={light?.text ?? DASH} tone={light?.tone ?? "neutral"} />
        <Stat label="Плохой день" value={rub(rubVar) ? `−${rub(rubVar)}` : DASH} sub={`${fmtPct(var95)} портфеля (VaR 95%)`} tone="down" />
        <Stat label="Очень плохой день" value={nav && es != null ? `−${rub(es * nav)}` : DASH} sub={`${fmtPct(es)} в среднем в 2,5% худших дней`} tone="down" />
        <Stat label="Худшая просадка за год" value={fmtPct(dd)} sub={beta != null ? `бета к рынку ${beta.toFixed(2)}` : undefined} />
      </StatGrid>
      {vol != null ? <Quiet>Годовая волатильность портфеля — {fmtPct(vol, 1)}: примерно так сильно портфель может отклониться за год в обычных условиях.</Quiet> : null}
      <Link href="/futures" className="inline-flex text-xs text-terminal-accent hover:underline">
        Снизить риск без продажи бумаг — защита фьючерсом →
      </Link>
    </Block>
  );
}

const fmtPct = (v: number | null | undefined, d = 2) => (v == null || !Number.isFinite(v) ? DASH : `${(Math.abs(v) * 100).toLocaleString("ru-RU", { maximumFractionDigits: d })}%`);

export function PortfolioRiskProfileView() {
  const { user } = useAuth();
  const { data, isLoading, error } = useQuery({
    queryKey: ["portfolio-risk-analytics"],
    queryFn: () => portfolioApi.riskAnalytics(),
  });
  const { data: engine } = useQuery({
    queryKey: ["risk-engine", user?.id],
    queryFn: () => portfolioApi.riskEngine(undefined, "paper"),
  });

  if (isLoading && !engine) {
    return (
      <div className="space-y-3">
        <Skeleton className="h-24" />
        <Skeleton className="h-48" />
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {engine ? <RiskSummary engine={engine as UnifiedRiskSnapshot & Record<string, unknown>} /> : null}
      <RiskAttributionPanel snapshot={engine} userId={user?.id} />
      <FactorCompositionPanel />
      {error || !data || !(data.holdings ?? []).length ? null : <RiskBody data={data} engine={engine} />}
    </div>
  );
}

type EngineRisk = {
  var_95?: number;
  var_99?: number;
  es_975?: number;
} | null | undefined;

function buildVerdict(data: PortfolioRiskAnalytics, engine: EngineRisk): string[] {
  const lines: string[] = [];
  const nav = data.nav_usd ?? 0;
  const var95 = engine?.var_95 ?? null;
  const beta = data.beta;
  const conc = data.concentration_share;
  const corr = data.avg_pairwise_correlation;
  const alpha = data.alpha;
  const holdings = data.holdings ?? [];
  const shorts = holdings.filter((h) => (h.weight ?? 0) < 0 || (h.notional_usd ?? 0) < 0);
  const longShare = holdings
    .filter((h) => (h.weight ?? 0) > 0)
    .reduce((s, h) => s + Math.abs(h.weight ?? 0), 0);
  const shortShare = holdings
    .filter((h) => (h.weight ?? 0) < 0)
    .reduce((s, h) => s + Math.abs(h.weight ?? 0), 0);

  const varUsd = var95 != null && nav > 0 ? var95 * nav : null;
  if (nav > 0 && var95 != null) {
    if (var95 >= 0.05) {
      lines.push(
        `Дневной VaR 95 ≈ ${pct(var95)} от капитала (~${usd(varUsd)}): портфель чувствителен к резким дням — размер позиций лучше держать скромнее.`,
      );
    } else if (var95 >= 0.025) {
      lines.push(
        `Дневной VaR 95 ≈ ${pct(var95)} (~${usd(varUsd)}): риск умеренный, но один плохой день всё ещё заметен относительно NAV ${usd(nav)}.`,
      );
    } else {
      lines.push(
        `Дневной VaR 95 ≈ ${pct(var95)} (~${usd(varUsd)}): при текущем NAV ${usd(nav)} просадка от «обычного» плохого дня выглядит умеренной.`,
      );
    }
  }

  if (beta != null) {
    if (beta <= -0.3) {
      lines.push(
        `Бета ${beta.toFixed(2)}: портфель скорее движется против широкого рынка — хедж или шорты доминируют над лонгами.`,
      );
    } else if (beta >= 1.2) {
      lines.push(
        `Бета ${beta.toFixed(2)}: портфель усиливает движения рынка — в рисковые дни просадка может быть сильнее индекса.`,
      );
    } else if (Math.abs(beta) < 0.35) {
      lines.push(
        `Бета ${beta.toFixed(2)}: слабая связь с широким рынком — результат больше зависит от отдельных идей, чем от индекса.`,
      );
    } else {
      lines.push(
        `Бета ${beta.toFixed(2)}: портфель в целом идёт примерно в ногу с рынком, без сильного плеча.`,
      );
    }
  }

  if (shorts.length > 0) {
    lines.push(
      `Открытых шортов: ${shorts.length} (суммарный вес ≈ ${pct(shortShare, 0)}). Лонги ≈ ${pct(longShare, 0)}. Это объясняет отрицательные нотионалы в таблице.`,
    );
  }

  if (conc != null) {
    if (conc >= 0.45) {
      lines.push(
        `Концентрация ${pct(conc, 0)}: значимая доля капитала в 1–2 бумагах — ошибка по одному тикеру бьёт по всему счёту.`,
      );
    } else if (conc <= 0.2) {
      lines.push(`Концентрация ${pct(conc, 0)}: капитал размазан шире — одиночная идея реже ломает день.`);
    } else {
      lines.push(`Концентрация ${pct(conc, 0)}: умеренная — есть ядро позиций, но не полный «all-in».`);
    }
  }

  if (corr != null) {
    if (corr >= 0.55) {
      lines.push(
        `Средняя корреляция ${pct(corr, 0)}: позиции ходят похоже — диверсификация слабее, чем кажется по числу тикеров.`,
      );
    } else if (corr <= 0.25) {
      lines.push(
        `Средняя корреляция ${pct(corr, 0)}: идеи относительно независимы — это плюс к устойчивости портфеля.`,
      );
    }
  }

  if (alpha != null && Number.isFinite(alpha)) {
    if (alpha > 0.2) {
      lines.push(
        `Альфа (год.) ${pct(alpha)}: на истории портфель обгонял бенчмарк с поправкой на бету — но это не гарантия вперёд.`,
      );
    } else if (alpha < -0.1) {
      lines.push(
        `Альфа (год.) ${pct(alpha)}: на истории портфель отставал от бенчмарка с поправкой на риск — стоит пересмотреть ядро идей.`,
      );
    }
  }

  if (!lines.length) {
    lines.push("Пока мало данных для вердикта — откройте позиции или дождитесь накопления истории доходностей.");
  }
  return lines.slice(0, 6);
}

function metricExplain(
  key: string,
  data: PortfolioRiskAnalytics,
  engine: EngineRisk,
): { label: string; hint: string } {
  const nav = data.nav_usd ?? 0;
  const var95 = engine?.var_95;
  const var99 = engine?.var_99;
  const es = engine?.es_975;
  switch (key) {
    case "nav":
      return {
        label: "Стоимость портфеля (NAV)",
        hint: "Текущая оценка открытых позиций и кэша в долларах.",
      };
    case "var95":
      return {
        label: "VaR 95%",
        hint: `С вероятностью около 95% дневной убыток не превысит ${pct(var95)} (примерно ${usd(var95 != null && nav ? var95 * nav : null)}).`,
      };
    case "var99":
      return {
        label: "VaR 99%",
        hint: `Более жёсткий хвост: в ~1% худших дней убыток может доходить до ${pct(var99)} (~${usd(var99 != null && nav ? var99 * nav : null)}).`,
      };
    case "es95":
      return {
        label: "Ожидаемый хвост",
        hint: `Если день уже среди худших, средний убыток около ${pct(es)} (примерно ${usd(es != null && nav ? es * nav : null)}).`,
      };
    case "beta":
      return {
        label: "Бета",
        hint: "Чувствительность к широкому рынку: 1 ≈ как индекс, <0 ≈ чаще против рынка.",
      };
    case "alpha":
      return {
        label: "Альфа (год.)",
        hint: "Доходность сверх того, что объясняет бета к рынку (историческая оценка).",
      };
    case "corr":
      return {
        label: "Ср. корреляция",
        hint: "Насколько позиции ходят вместе. Высокая — «много тикеров, одна ставка».",
      };
    case "conc":
      return {
        label: "Концентрация",
        hint: "Доля крупнейших позиций в портфеле. Высокая — риск одной идеи.",
      };
    default:
      return { label: key, hint: "" };
  }
}

function RiskBody({
  data,
  engine,
}: {
  data: PortfolioRiskAnalytics;
  engine: EngineRisk;
}) {
  const methodology = "Оценка возможного дневного убытка по прошлым движениям портфеля. Это не обещание результата.";
  const verdict = buildVerdict(data, engine);
  const nav = data.nav_usd ?? 0;
  const var95 = engine?.var_95;
  const var99 = engine?.var_99;
  const es = engine?.es_975;

  const metrics: Array<{ key: string; value: string; sub?: string }> = [
    { key: "nav", value: usd(data.nav_usd) },
    { key: "var95", value: pct(var95), sub: usd(var95 != null && nav ? var95 * nav : null) },
    { key: "var99", value: pct(var99), sub: usd(var99 != null && nav ? var99 * nav : null) },
    { key: "es95", value: pct(es), sub: usd(es != null && nav ? es * nav : null) },
    { key: "beta", value: data.beta?.toFixed(2) ?? "—" },
    { key: "alpha", value: pct(data.alpha) },
    { key: "corr", value: pct(data.avg_pairwise_correlation, 0) },
    { key: "conc", value: pct(data.concentration_share, 0) },
  ];

  return (
    <div className="space-y-4">
      <div className="cockpit-panel p-4">
        <div className="flex items-center gap-2 mb-3">
          <Shield size={16} className="text-terminal-accent" />
          <span className="font-semibold">Риск-профиль портфеля</span>
          <span className="text-xs text-qa-muted ml-auto">
            на {data.data_as_of?.slice(0, 10) || "—"}
          </span>
        </div>
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-3 text-sm">
          {metrics.map((m) => {
            const meta = metricExplain(m.key, data, engine);
            return (
              <div key={m.key} className="border border-cockpit-border/60 rounded px-2.5 py-2">
                <div className="text-[10px] uppercase tracking-wide text-qa-muted">{meta.label}</div>
                <div className="font-mono tabular-nums text-qa-text mt-0.5">
                  {m.value}
                  {m.sub ? <span className="text-qa-muted text-xs ml-1">({m.sub})</span> : null}
                </div>
                <p className="text-[10px] text-qa-muted mt-1 leading-snug">{meta.hint}</p>
              </div>
            );
          })}
        </div>
        <p className="text-[11px] text-qa-muted mt-3">{methodology}</p>
      </div>

      <div className="cockpit-panel p-4">
        <div className="cockpit-panel-header mb-2">Вердикт по вашему портфелю</div>
        <ul className="space-y-2 text-sm text-qa-text/90 leading-relaxed list-disc pl-5">
          {verdict.map((line) => (
            <li key={line.slice(0, 48)}>{line}</li>
          ))}
        </ul>
      </div>

      {data.holdings?.length > 0 && (
        <div className="cockpit-panel p-4 overflow-auto">
          <div className="cockpit-panel-header mb-2">Позиции</div>
          <table className="w-full text-xs font-mono">
            <thead>
              <tr className="text-qa-muted border-b border-cockpit-border">
                <th className="text-left py-1">Тикер</th>
                <th className="text-right py-1">Вес</th>
                <th className="text-right py-1">Нотионал</th>
                <th className="text-left py-1 pl-2">Сектор</th>
              </tr>
            </thead>
            <tbody>
              {data.holdings.map((h) => (
                <tr key={h.symbol} className="border-b border-cockpit-border/50">
                  <td className="py-1">{h.symbol}</td>
                  <td className="text-right">{pct(h.weight, 1)}</td>
                  <td className="text-right">{usd(h.notional_usd)}</td>
                  <td className="pl-2 text-qa-muted">{h.sector}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {data.stress?.length > 0 && (
        <div className="cockpit-panel p-4">
          <div className="cockpit-panel-header mb-2">Стресс-сценарии</div>
          <div className="grid gap-2 md:grid-cols-2">
            {data.stress.map((s) => (
              <div key={s.scenario_id} className="border border-cockpit-border rounded p-2 text-xs">
                <div className="font-semibold">{s.label_ru}</div>
                <div className="text-qa-muted">
                  {s.start} → {s.end}
                </div>
                <div className="mt-1 font-mono">
                  доходность {pct(s.total_return)} · макс. просадка {pct(s.max_drawdown)}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {(data.notes || []).length > 0 && (
        <ul className="text-[11px] text-qa-muted list-disc pl-5">
          {data.notes.map((n) => (
            <li key={n}>{n}</li>
          ))}
        </ul>
      )}
    </div>
  );
}
