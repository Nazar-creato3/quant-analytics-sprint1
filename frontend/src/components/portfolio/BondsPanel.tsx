"use client";

import { useMutation, useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { fetchUiTexts } from "@/lib/legal-docs";
import { portfolioApi } from "@/lib/api";

type BondTexts = Record<string, string>;

function fmtPct(value: number | null | undefined, digits = 2): string {
  if (value == null || !Number.isFinite(value)) return "нет данных";
  return `${(value * 100).toFixed(digits)}%`;
}

function fmtNum(value: number | null | undefined, digits = 2): string {
  if (value == null || !Number.isFinite(value)) return "нет данных";
  return value.toFixed(digits);
}

export function BondsPanel({ portfolioId = "paper" }: { portfolioId?: string }) {
  const { data: texts } = useQuery({
    queryKey: ["legal-ui-texts-bonds"],
    queryFn: async () => {
      try {
        const data = (await fetchUiTexts()) as { bonds?: BondTexts };
        return data.bonds ?? {};
      } catch {
        return {};
      }
    },
    staleTime: 60_000,
  });
  const t = texts ?? {};
  const { data, isLoading, error } = useQuery({
    queryKey: ["portfolio-bonds", portfolioId],
    queryFn: () => portfolioApi.bonds(portfolioId),
  });
  const stress = useMutation({
    mutationFn: () => portfolioApi.bondStress(portfolioId, 200),
  });

  if (isLoading) {
    return (
      <section data-testid="bonds-panel" className="cockpit-panel p-4">
        <p className="text-sm text-qa-muted">загрузка</p>
      </section>
    );
  }
  // No bonds in the portfolio (or nothing computed) → the block is not shown.
  if (error || !data || data.status === "flag_off" || !(data.issues ?? []).length) return null;

  const issues = data.issues ?? [];
  const summary = data.summary ?? {};
  const hot = data.ladder?.concentration ?? [];

  const fmtY = (v: unknown) => (v == null || !Number.isFinite(Number(v)) ? "—" : `${(Number(v) * 100).toLocaleString("ru-RU", { maximumFractionDigits: 2 })}%`);
  const fmtYears = (v: unknown) => (v == null || !Number.isFinite(Number(v)) ? "—" : `${Number(v).toLocaleString("ru-RU", { maximumFractionDigits: 1 })} г.`);
  const fmtDate = (v: unknown) => (v ? new Date(String(v)).toLocaleDateString("ru-RU", { day: "numeric", month: "long", year: "numeric" }) : "—");

  return (
    <section data-testid="bonds-panel" className="card p-5 space-y-4">
      <header className="flex items-start justify-between gap-3">
        <div>
          <h2 className="text-sm font-semibold">{t.title ?? "Облигации"}</h2>
          <p className="text-xs text-qa-muted mt-1 max-w-2xl" data-testid="bonds-source">
            Доходность, если держать до погашения, и срок, за который в среднем возвращаются деньги. Источник — {String(data.source ?? "биржа")}, данные на {fmtDate(data.as_of)}.
          </p>
        </div>
        <Link className="shrink-0 text-[11px] text-qa-muted hover:text-terminal-accent hover:underline" href="/methodology/bonds" data-testid="bonds-method">
          Как считается
        </Link>
      </header>
      <div className="grid gap-3 grid-cols-2 lg:grid-cols-4" data-testid="bonds-summary">
        <div className="rounded-lg border border-cockpit-border bg-cockpit-panel-raised px-4 py-3">
          <p className="text-[11px] uppercase tracking-wide text-qa-muted">Доходность к погашению</p>
          <p className="mt-1 text-lg font-semibold tabular-nums text-terminal-up">{fmtY(summary.ytm)}</p>
          <p className="text-[11px] text-qa-muted">в среднем по облигациям, до НДФЛ</p>
        </div>
        <div className="rounded-lg border border-cockpit-border bg-cockpit-panel-raised px-4 py-3">
          <p className="text-[11px] uppercase tracking-wide text-qa-muted">Дюрация</p>
          <p className="mt-1 text-lg font-semibold tabular-nums">{fmtYears(summary.duration)}</p>
          <p className="text-[11px] text-qa-muted">средний срок возврата денег</p>
        </div>
      </div>
      <table className="w-full text-xs" data-testid="bonds-table">
        <thead>
          <tr className="text-qa-muted text-left border-b border-cockpit-border">
            <th className="py-1.5 font-normal">Облигация</th>
            <th className="font-normal text-right">Доходность</th>
            <th className="font-normal text-right">Дюрация</th>
            <th className="font-normal text-right">Купон в год, после налога</th>
            <th className="font-normal text-right">Ближайшая выплата</th>
          </tr>
        </thead>
        <tbody>
          {issues.map((row: Record<string, unknown>) => (
            <tr key={String(row.figi)} className="border-b border-cockpit-border/50">
              <td className="py-1.5">
                <Link className="font-medium hover:text-terminal-accent" href={`/bonds/${row.figi}`}>
                  {String(row.name ?? row.secid ?? row.figi)}
                </Link>
                {row.name && row.name !== row.secid ? <span className="ml-1 text-qa-muted">{String(row.secid ?? "")}</span> : null}
                {row.floater ? <span className="ml-1 text-terminal-accent">· плавающий купон</span> : null}
              </td>
              <td className="text-right tabular-nums">{row.excluded ? "—" : fmtY(row.ytm)}</td>
              <td className="text-right tabular-nums">{row.excluded ? "—" : fmtYears(row.duration)}</td>
              <td className="text-right tabular-nums">
                {row.coupon_net == null ? "—" : `${Number(row.coupon_net).toLocaleString("ru-RU", { maximumFractionDigits: 0 })} ₽`}
              </td>
              <td className="text-right">{fmtDate(row.next_event)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {hot.length > 0 && issues.length > 1 ? (
        <p className="text-xs text-terminal-accent" data-testid="bonds-ladder">
          Больше 30% денег от облигаций вернутся в одном квартале ({hot.join(", ")}) — их придётся вкладывать заново по той ставке, что будет тогда.
        </p>
      ) : null}
      <div data-testid="bonds-stress" className="flex flex-wrap items-center gap-3">
        <button type="button" className="btn-ghost text-xs" data-testid="bonds-stress-run" onClick={() => stress.mutate()}>
          Что будет, если ставки вырастут на 2 п.п.
        </button>
        {stress.data ? (
          <p className="text-sm" data-testid="bonds-stress-result">
            Облигации подешевеют на{" "}
            <b className="text-terminal-down">
              {Math.abs(Number(stress.data.delta_rub) || 0).toLocaleString("ru-RU", { maximumFractionDigits: 0 })} ₽
            </b>{" "}
            ({fmtY(Math.abs(Number(stress.data.delta_pct_portfolio) || 0))} их стоимости)
          </p>
        ) : null}
      </div>
    </section>
  );
}
