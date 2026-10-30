"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { forecastApi } from "@/lib/api";
import { useAuth } from "@/hooks";
import { useProductContext } from "@/contexts/ProductContext";
import { queryKeys } from "@/lib/queryKeys";
import { DataState, ProvenanceBadge } from "@/components/shared/DataState";
import { ManeuverControlBlock } from "@/components/act/ManeuverControlBlock";
import { FundReportPanel } from "@/components/report/FundReportPanel";
import type { ControlRow } from "@/lib/maneuver-control";

const QUEUE_LABEL: Record<string, string> = {
  q1_composition: "состав",
  q2_var_stress: "риск",
  q3_returns: "доходность",
  q4_unrated_bonds: "облигации без рейтинга",
  q5_full_stress: "стресс",
};

function queueStatus(raw: string | undefined): string {
  if (raw === "ready") return "есть данные";
  if (raw === "beta" || raw === "partial") return "частично";
  return "нет данных";
}

const RISK_LIGHT: Record<string, string> = {
  green: "спокойно",
  yellow: "повышенный",
  red: "высокий",
  gray: "нет данных",
};

function riskScale(light: unknown, status: unknown): string {
  const tone = RISK_LIGHT[String(light ?? "")] || "нет данных";
  if (status === "beta" || status === "partial") return `${tone} · частично`;
  return tone;
}

function Metric({
  title,
  value,
  meaning,
  rubles,
  source,
  asOf,
  status,
}: {
  title: string;
  value: string;
  meaning: { phrase: string; detail: string; learn: string };
  rubles?: string;
  source: string;
  asOf?: string;
  status: "ready" | "partial" | "beta";
}) {
  return (
    <article className="rounded-xl border border-qa-border p-3 space-y-1">
      <p className="text-[10px] uppercase text-qa-muted">{title}</p>
      <p className="text-sm" data-testid={`report-${title}`}>
        {value}
      </p>
      <p className="text-xs text-qa-muted">{meaning.phrase}</p>
      <details className="text-xs text-qa-muted">
        <summary>Что это значит</summary>
        <p>{meaning.detail}</p>
        <p className="mt-1">{meaning.learn}</p>
      </details>
      {rubles ? <p className="text-xs">В рублях: {rubles}</p> : null}
      <ProvenanceBadge source={source} asOf={asOf} status={status} />
    </article>
  );
}

export function PortfolioReportCard() {
  const { user } = useAuth();
  const { mode } = useProductContext();
  const sessionUserId = user?.id;
  const { data, isLoading, isError } = useQuery({
    queryKey: queryKeys.report(sessionUserId || "anonymous", mode),
    enabled: Boolean(sessionUserId),
    queryFn: () => forecastApi.report(sessionUserId as string, mode),
  });
  const first = data?.first_screen;
  const empty = Boolean(data?.empty || data?.demo || first?.data_status === "нет данных");
  const status = empty ? "partial" : "ready";
  const asOf = first?.as_of || data?.as_of;
  const nd = "нет данных";
  const queues = data?.queues || {};

  return (
    <DataState loading={isLoading} error={isError} empty={false} loadingText="Отчёт: загрузка…" errorText="Отчёт: нет данных">
      <div className="space-y-4" data-testid="portfolio-report">
        <div className="cockpit-panel p-4">
          <p className="text-[10px] uppercase tracking-wide text-qa-muted">Первый экран</p>
          <p className="text-sm mt-1">{data?.headline}</p>
          <p className="text-xs text-qa-muted mt-1">
            {data?.demo ? "Учебный пример: в книге нет позиций. " : ""}
            {data?.disclaimer}
          </p>
          <ProvenanceBadge source="отчёт" status={status} asOf={asOf} />
        </div>

        <div className="grid gap-3 md:grid-cols-2">
          <Metric
            title="TWR"
            value={first?.twr != null ? String(first.twr) : nd}
            meaning={{ phrase: "Доходность без учёта пополнений и выводов.", detail: "Считается по книге портфеля.", learn: "Так сравнивают счета с разными вводами денег." }}
            source="доходность"
            asOf={asOf}
            status={status}
          />
          <Metric
            title="MWR"
            value={first?.mwr != null ? String(first.mwr) : nd}
            meaning={{ phrase: "Доходность с учётом пополнений и выводов.", detail: "Считается по той же книге.", learn: "Ближе к тому, что видно на счёте." }}
            source="доходность"
            asOf={asOf}
            status={status}
          />
          <Metric
            title="Потери в кризис"
            value={first?.crisis ? String(first.crisis.pnl ?? first.crisis.id ?? nd) : nd}
            meaning={{ phrase: "Как портфель вёл себя в прошлом кризисе.", detail: "Это прошлое движение, не прогноз.", learn: "Смотрите, хватает ли истории по бумагам." }}
            source="прошлый кризис"
            asOf={asOf}
            status={status}
          />
          <Metric
            title="Концентрация"
            value={first?.hhi != null ? String(first.hhi) : nd}
            meaning={{ phrase: "Насколько портфель зависит от немногих позиций.", detail: "Чем выше число, тем сильнее зависимость.", learn: "Один расчёт на весь отчёт." }}
            rubles={first?.rubles_var_95 != null ? String(first.rubles_var_95) : undefined}
            source="концентрация"
            asOf={asOf}
            status={status}
          />
        </div>

        <FundReportPanel fund={data?.fund} />

        <section className="cockpit-panel p-4 space-y-2">
          <p className="text-[10px] uppercase text-qa-muted">Доходность против ориентира</p>
          <p className="text-xs text-qa-muted" data-testid="report-equity-vs-bench">
            {first?.equity_vs_benchmark?.data_status === "нет данных"
              ? "нет данных"
              : `${String(first?.equity_vs_benchmark?.benchmark_id || "")} · ${
                  Array.isArray(first?.equity_vs_benchmark?.points)
                    ? first.equity_vs_benchmark.points.length
                    : 0
                } точек`}
          </p>
          {first?.equity_vs_benchmark?.data_status === "ok" && Array.isArray(first?.equity_vs_benchmark?.points) ? (
            <p className="text-xs" data-testid="report-equity-last">
              портфель {String(first.equity_vs_benchmark.points.at(-1)?.portfolio ?? "нет данных")}
              {first.equity_vs_benchmark.points.at(-1)?.benchmark != null
                ? ` · ориентир ${String(first.equity_vs_benchmark.points.at(-1)?.benchmark)}`
                : ""}
            </p>
          ) : null}
          {first?.equity_vs_benchmark?.benchmark_note ? (
            <p className="text-xs text-qa-muted">{String(first.equity_vs_benchmark.benchmark_note)}</p>
          ) : null}
        </section>

        <section className="cockpit-panel p-4 space-y-2">
          <p className="text-[10px] uppercase text-qa-muted">Карта концентрации</p>
          {(first?.concentration_map || []).length ? (
            <ul className="space-y-1">
              {(first?.concentration_map || []).slice(0, 12).map((row) => (
                <li key={String(row.ticker)} className="text-xs">
                  <Link className="underline text-terminal-accent" href={`/screener?symbol=${encodeURIComponent(String(row.ticker))}`}>
                    {String(row.ticker)}
                  </Link>
                  <span className="ml-2">{String(row.weight)}</span>
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-xs text-qa-muted">нет данных</p>
          )}
        </section>

        <section className="cockpit-panel p-4 space-y-1">
          <p className="text-[10px] uppercase text-qa-muted">Шкала риска</p>
          <p className="text-xs" data-testid="report-risk-scale">
            {riskScale(first?.traffic_light, first?.risk_status)}
          </p>
        </section>

        <section className="cockpit-panel p-4">
          <p className="text-[10px] uppercase text-qa-muted">Календарь событий</p>
          <p className="text-xs text-qa-muted">{first?.events_calendar?.data_status || nd}</p>
        </section>

        <section className="cockpit-panel p-4 space-y-2">
          <p className="text-[10px] uppercase text-qa-muted">Стресс</p>
          {(data?.stress?.scenarios || []).length ? (
            <ul className="space-y-1">
              {(data?.stress?.scenarios || []).slice(0, 8).map((row) => {
                const label = String(row.title || "сценарий");
                const id = String(row.id || label);
                const raw = Number(row.pnl_pct ?? row.pnl ?? 0);
                const width = Number.isFinite(raw) ? Math.min(100, Math.abs(raw) * (Math.abs(raw) <= 1 ? 100 : 1)) : 0;
                return (
                  <li key={id} className="text-xs">
                    <span className="text-qa-muted">{label}</span>
                    <span className="ml-2 inline-block h-2 bg-qa-border" style={{ width: `${width}%` }} />
                  </li>
                );
              })}
            </ul>
          ) : (
            <p className="text-xs text-qa-muted">нет данных</p>
          )}
        </section>

        <section className="cockpit-panel p-4">
          <p className="text-[10px] uppercase text-qa-muted">Блоки</p>
          <ul className="text-xs text-qa-muted">
            {Object.entries(queues).map(([k, v]) => (
              <li key={k}>
                {QUEUE_LABEL[k] || "блок"}: {queueStatus(v?.status)}
              </li>
            ))}
          </ul>
        </section>

        {data?.changed?.length ? (
          <p className="text-xs">Что изменилось: {data.changed.join(", ")}</p>
        ) : (
          <p className="text-xs text-qa-muted">Сравнения с прошлой версией пока нет.</p>
        )}

        <ManeuverControlBlock
          status={String(data?.maneuver_control?.status || "")}
          items={(data?.maneuver_control?.items || []) as ControlRow[]}
        />

        <div className="flex flex-wrap gap-2 text-xs">
          <Link className="underline text-terminal-accent" href="/portfolio?tab=risk">
            Проверить риск
          </Link>
          <Link className="underline text-terminal-accent" href="/chat">
            Спросить ИИ с контекстом
          </Link>
          <Link className="underline text-qa-muted" href="/sandbox">
            Песочница
          </Link>
          <button
            type="button"
            data-testid="k6-pdf"
            className="underline text-terminal-accent"
            onClick={async () => {
              if (!sessionUserId) return;
              const blob = await forecastApi.reportPdf(sessionUserId, mode);
              const url = URL.createObjectURL(blob);
              const a = document.createElement("a");
              a.href = url;
              a.download = "portfolio-report.pdf";
              a.click();
              URL.revokeObjectURL(url);
            }}
          >
            Скачать PDF
          </button>
        </div>
      </div>
    </DataState>
  );
}
