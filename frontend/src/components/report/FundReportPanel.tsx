"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { fetchUiTexts } from "@/lib/legal-docs";

type K1Alt = {
  ticker?: string;
  label?: string;
  data_status?: string;
  twr?: string | null;
  mwr?: string | null;
  diff_twr_pp?: string | null;
};

type FundBlock = {
  cagr?: number | null;
  max_dd?: number | null;
  sharpe?: number | null;
  monthly?: Array<{ year?: number; month?: string; return?: number }>;
  k1?: {
    status?: string;
    data_status?: string;
    reason?: string | null;
    alternatives?: K1Alt[];
  };
  attribution?: {
    enb?: number | null;
    components?: Array<{ ticker?: string; weight?: number; pct_of_vol?: number; pct_of_cvar?: number }>;
  };
  factors?: IslandBlock;
  stress_rate?: IslandBlock;
  futures?: IslandBlock;
  goals?: IslandBlock;
  bonds?: IslandBlock;
  income?: IslandBlock;
  look_through?: IslandBlock;
  liquidity?: IslandBlock;
  data_status?: string;
};

type IslandBlock = {
  status?: string;
  reason?: string | null;
  sentence?: string | null;
  enb?: number | null;
  probability?: number | null;
};

type K6Texts = Record<string, string>;

function pct(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return "нет данных";
  return `${(value * 100).toFixed(1)}%`;
}

export function FundReportPanel({ fund }: { fund?: FundBlock | null }) {
  const { data: texts } = useQuery({
    queryKey: ["legal-ui-texts-k6"],
    queryFn: fetchUiTexts,
    staleTime: 60_000,
  });
  const t = ((texts?.k6 as K6Texts) || {}) as K6Texts;
  if (!fund || fund.data_status === "off") return null;
  return (
    <section className="cockpit-panel p-4 space-y-3" data-testid="k6-fund">
      <p className="text-[10px] uppercase text-qa-muted">{t.title || "Как вёл себя портфель"}</p>
      <div className="grid gap-3 md:grid-cols-3">
        <p className="text-xs" data-testid="k6-cagr">
          {t.cagr || "CAGR"}: {pct(fund.cagr)}
        </p>
        <p className="text-xs" data-testid="k6-max-dd">
          {t.max_dd || "просадка"}: {pct(fund.max_dd)}
        </p>
        <p className="text-xs" data-testid="k6-sharpe">
          {t.sharpe || "Sharpe"}: {fund.sharpe == null ? "нет данных" : String(fund.sharpe)}
        </p>
      </div>
      <div className="space-y-1" data-testid="k6-k1">
        <p className="text-xs text-qa-muted" data-testid="k6-k1-later">
          {t.vs_k1}
        </p>
        {(fund.k1?.alternatives || []).length ? (
          <ul className="text-xs space-y-1" data-testid="k6-k1-table">
            {(fund.k1?.alternatives || []).map((row) => (
              <li key={String(row.ticker)} data-testid={`k6-k1-${row.ticker}`}>
                {row.label || row.ticker}: TWR {row.twr ?? "нет данных"}
                {row.diff_twr_pp != null ? ` · разница ${row.diff_twr_pp} п.п.` : ""}
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-xs text-qa-muted" data-testid="k6-k1-empty">
            {fund.k1?.reason || "нет данных"}
          </p>
        )}
      </div>
      <div data-testid="k6-risk">
        <p className="text-xs" data-testid="k6-enb">
          {t.risk} · ENB{" "}
          {fund.attribution?.enb == null ? "нет данных" : Number(fund.attribution.enb).toFixed(2)}
        </p>
        {(fund.attribution?.components || []).length ? (
          <ul className="text-xs mt-1 space-y-1" data-testid="k6-risk-table">
            {(fund.attribution?.components || []).slice(0, 12).map((row) => (
              <li key={String(row.ticker)}>{row.ticker}</li>
            ))}
          </ul>
        ) : null}
      </div>
      <div data-testid="k6-monthly">
        <p className="text-[10px] uppercase text-qa-muted">{t.monthly || "По месяцам"}</p>
        {(fund.monthly || []).length ? (
          <ul className="text-xs grid gap-1 md:grid-cols-4">
            {(fund.monthly || []).slice(0, 12).map((row) => (
              <li key={`${row.year}-${row.month}`}>
                {row.year}-{row.month}: {pct(row.return)}
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-xs text-qa-muted">нет данных</p>
        )}
      </div>
      <div className="space-y-1" data-testid="k6-islands">
        <p className="text-xs" data-testid="k6-factors">
          факторы: {fund.factors?.status ?? "нет данных"} · {fund.factors?.reason || fund.factors?.sentence || "нет данных"}
        </p>
        <p className="text-xs" data-testid="k6-stress-rate">
          ставка: {fund.stress_rate?.status ?? "нет данных"} · {fund.stress_rate?.reason || fund.stress_rate?.sentence || "нет данных"}
        </p>
        <p className="text-xs" data-testid="k6-futures">
          фьючерсы: {fund.futures?.status ?? "нет данных"} · {fund.futures?.reason || "нет данных"}
        </p>
        <p className="text-xs" data-testid="k6-goals">
          цель: {fund.goals?.status ?? "нет данных"} · {fund.goals?.reason || "нет данных"}
        </p>
        <p className="text-xs" data-testid="k6-bonds">
          облигации: {fund.bonds?.status ?? "нет данных"} · {fund.bonds?.reason || "нет данных"}
        </p>
        <p className="text-xs" data-testid="k6-income">
          выплаты: {fund.income?.status ?? "нет данных"} · {fund.income?.reason || "нет данных"}
        </p>
        <p className="text-xs" data-testid="k6-look-through">
          сквозной взгляд: {fund.look_through?.status ?? "нет данных"} · {fund.look_through?.reason || "нет данных"}
        </p>
        <p className="text-xs" data-testid="k6-liquidity">
          ликвидность: {fund.liquidity?.status ?? "нет данных"} · {fund.liquidity?.reason || "нет данных"}
        </p>
      </div>
      <p className="text-xs text-qa-muted">{t.basis}</p>
      <div className="flex flex-wrap gap-3">
        <Link className="text-xs underline text-terminal-accent" href="/methodology">
          {t.method_link || "Как это считается"}
        </Link>
        <Link className="text-xs underline text-terminal-accent" href="/statement-review">
          {t.statement_title || "Разбор по выписке брокера"}
        </Link>
      </div>
    </section>
  );
}
