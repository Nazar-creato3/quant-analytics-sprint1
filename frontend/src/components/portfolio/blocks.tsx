"use client";

import { useMemo, useState } from "react";
import { clsx } from "clsx";
import { useQuery } from "@tanstack/react-query";
import { accountApi, portfolioApi } from "@/lib/api";
import { useProductContext } from "@/contexts/ProductContext";
import { Block, DASH, Quiet, Stat, StatGrid, pct, rub } from "./ui";

/* ── Ставка ЦБ: what a key-rate move does to this portfolio + rates of major central banks ── */

const CB: Array<{ id: string; name: string }> = [
  { id: "CBR_KEY_RATE", name: "Банк России" },
  { id: "FED_FUNDS_RATE", name: "ФРС США" },
  { id: "ECB_DEPOSIT_RATE", name: "ЕЦБ" },
  { id: "BOE_BANK_RATE", name: "Банк Англии" },
  { id: "BOJ_POLICY_RATE", name: "Банк Японии" },
  { id: "PBOC_POLICY_RATE", name: "Народный банк Китая" },
  { id: "BOC_OVERNIGHT_RATE", name: "Банк Канады" },
  { id: "SE_POLICY_RATE", name: "Риксбанк (Швеция)" },
];

export function KeyRateBlock() {
  const { mode } = useProductContext();
  const [shift, setShift] = useState(100);
  const { data, isLoading } = useQuery({
    queryKey: ["pf-key-rate", shift, mode],
    queryFn: () => portfolioApi.keyRate(shift, mode),
  });
  const { data: rates } = useQuery({
    queryKey: ["pf-cb-rates"],
    queryFn: () => portfolioApi.centralBankRates(CB.map((c) => c.id)),
    staleTime: 10 * 60_000,
  });
  const byId = useMemo(() => new Map((rates || []).map((r) => [r.instrument, r])), [rates]);
  const shown = CB.filter((c) => byId.has(c.id));
  // value_change is 0 when every paper was skipped — that is «нет оценки», not «не изменится».
  const change = (data as { nav?: number | null } | undefined)?.nav == null ? null : data?.value_change;
  const sign = shift > 0 ? "+" : "";

  return (
    <Block
      title="Ставки центральных банков"
      hint="Что будет со стоимостью портфеля и денежным доходом, если Банк России изменит ключевую ставку. Оценка по прошлой реакции рынка, не прогноз."
      method="/methodology/key-rate"
      testId="k63-key-rate"
    >
      {shown.length ? (
        <div className="grid gap-2 grid-cols-2 md:grid-cols-4" data-testid="cb-rates">
          {shown.map((c) => {
            const r = byId.get(c.id)!;
            return (
              <div key={c.id} className="rounded-lg border border-cockpit-border px-3 py-2">
                <p className="text-[11px] text-qa-muted">{c.name}</p>
                <p className="text-base font-semibold tabular-nums">{pct(r.value, 2, false)}</p>
                <p className="text-[10px] text-qa-muted">на {String(r.period || r.observation_time).slice(0, 10)}</p>
              </div>
            );
          })}
        </div>
      ) : (
        <Quiet>Ставки центральных банков загружаются ночью; появятся после первой загрузки данных.</Quiet>
      )}

      <div className="rounded-lg border border-cockpit-border p-4 space-y-3">
        <label className="flex flex-wrap items-center gap-3 text-xs" htmlFor="kr-shift">
          <span className="font-medium">Если ключевая ставка изменится на</span>
          <input
            id="kr-shift"
            type="range"
            min={-300}
            max={300}
            step={25}
            value={shift}
            onChange={(e) => setShift(Number(e.target.value))}
            className="w-56 accent-[var(--qa-accent)]"
            data-testid="k63-slider"
          />
          <span className="tabular-nums font-semibold text-terminal-accent">
            {sign}
            {(shift / 100).toLocaleString("ru-RU", { minimumFractionDigits: 2 })} п.п.
          </span>
        </label>
        <StatGrid>
          <Stat
            label="Стоимость портфеля"
            value={isLoading ? "…" : rub(change) ?? DASH}
            tone={change == null ? "neutral" : change >= 0 ? "up" : "down"}
            sub="изменение"
          />
          <Stat label="Денежный доход за 12 мес." value={isLoading ? "…" : rub(data?.income_12m) ?? DASH} sub={data?.income_note_ru || "доход от ставки"} />
        </StatGrid>
        {!isLoading && change == null ? (
          <Quiet>Оценка появится, когда по бумагам портфеля наберётся история цен.</Quiet>
        ) : null}
        {change != null && data?.sentence ? <p className="text-xs text-qa-muted" data-testid="k63-sentence">{data.sentence}</p> : null}
      </div>
    </Block>
  );
}

/* ── Выплаты ── */

const PAYOUT_LABEL: Record<string, string> = {
  dividend: "дивиденд",
  coupon: "купон",
  fund_payout: "выплата фонда",
  amortization: "амортизация",
  redemption: "погашение",
};

const MONTH_RU = ["янв", "фев", "мар", "апр", "май", "июн", "июл", "авг", "сен", "окт", "ноя", "дек"];

type PayoutEvent = {
  date?: string;
  type?: string;
  amount_net_rub?: number | null;
  status?: string;
  instrument?: { ticker?: string };
};

export function PayoutsBlock() {
  const { data, isLoading } = useQuery({ queryKey: ["pf-cashflows"], queryFn: () => portfolioApi.cashflows("paper") });
  const { data: summary } = useQuery({ queryKey: ["pf-cashflow-summary"], queryFn: () => portfolioApi.cashflowSummary("paper", 12) });
  const today = new Date().toISOString().slice(0, 10);
  const upcoming = ((data?.events ?? []) as PayoutEvent[])
    .filter((e) => String(e.date || "") >= today)
    .sort((a, b) => String(a.date).localeCompare(String(b.date)))
    .slice(0, 12);
  const byMonth = (summary?.by_month ?? {}) as Record<string, { net?: number; estimated_net?: number }>;
  // Always 12 months from now, so empty months read as «ничего не придёт», not as a gap.
  const months: Array<[string, { net?: number; estimated_net?: number }]> = Array.from({ length: 12 }, (_, i) => {
    const d = new Date();
    d.setDate(1);
    d.setMonth(d.getMonth() + i);
    const key = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
    return [key, byMonth[key] ?? { net: 0 }];
  });
  const max = Math.max(1, ...months.map(([, v]) => v.net ?? 0));
  const total12 = months.reduce((acc, [, v]) => acc + (v.net ?? 0), 0);
  const est12 = months.reduce((acc, [, v]) => acc + (v.estimated_net ?? 0), 0);
  const fmtDay = (d?: string) => (d ? new Date(d).toLocaleDateString("ru-RU", { day: "numeric", month: "long" }) : DASH);

  return (
    <Block
      title="Выплаты"
      hint="Дивиденды, купоны и выплаты фондов по вашим бумагам на 12 месяцев вперёд, после оценки налога."
      method="/methodology/payouts"
      testId="payout-calendar"
    >
      <StatGrid>
        <Stat label="За 12 месяцев" value={rub(total12) ?? DASH} tone="up" sub={est12 > 0 ? `из них ${rub(est12)} — оценка по прошлому году` : "после НДФЛ 13%"} />
        <Stat label="Уже объявлено" value={rub(total12 - est12) ?? DASH} />
        <Stat label="Ближайшая выплата" value={upcoming[0] ? fmtDay(upcoming[0].date) : DASH} sub={upcoming[0]?.instrument?.ticker} />
      </StatGrid>
      {total12 > 0 ? (
        <div className="flex items-end gap-1 h-28" data-testid="payout-chart" aria-label="Поступления по месяцам">
          {months.map(([m, v]) => (
            <div key={m} className="flex-1 flex flex-col items-center gap-1 min-w-0">
              <div className="w-full flex flex-col justify-end" style={{ height: 88 }} title={`${m}: ${rub(v.net) ?? DASH}${v.estimated_net ? `, из них оценка ${rub(v.estimated_net)}` : ""}`}>
                {v.estimated_net ? (
                  <div className="w-full rounded-t border border-dashed border-terminal-accent/70" style={{ height: `${(v.estimated_net / max) * 88}px` }} />
                ) : null}
                <div
                  className={clsx("w-full", !v.estimated_net && "rounded-t")}
                  style={{ height: `${Math.max(2, (((v.net ?? 0) - (v.estimated_net ?? 0)) / max) * 88)}px`, background: (v.net ?? 0) > 0 ? "var(--terminal-accent)" : "var(--qa-border, #444)" }}
                />
              </div>
              <span className="text-[9px] text-qa-muted">{MONTH_RU[Number(m.slice(5)) - 1]}</span>
            </div>
          ))}
        </div>
      ) : null}
      {est12 > 0 ? <Quiet>Сплошной столбец — объявленные выплаты, пунктир — оценка по выплате прошлого года (компания ещё не объявила).</Quiet> : null}
      {isLoading ? <Quiet>Загрузка…</Quiet> : null}
      {upcoming.length ? (
        <table className="w-full text-xs" data-testid="payout-list">
          <thead>
            <tr className="text-qa-muted text-left border-b border-cockpit-border">
              <th className="py-1.5 font-normal">Дата</th>
              <th className="font-normal">Бумага</th>
              <th className="font-normal">Тип</th>
              <th className="font-normal text-right">Сумма</th>
            </tr>
          </thead>
          <tbody>
            {upcoming.map((e) => (
              <tr key={`${e.date}-${e.instrument?.ticker}-${e.type}`} className="border-b border-cockpit-border/50">
                <td className="py-1.5 tabular-nums">{fmtDay(e.date)}</td>
                <td className="font-medium">{e.instrument?.ticker}</td>
                <td className="text-qa-muted">
                  {PAYOUT_LABEL[e.type || ""] ?? e.type}
                  {e.status === "estimated" ? " · ориентир" : ""}
                </td>
                <td className="text-right tabular-nums">{rub(e.amount_net_rub, 2) ?? <span className="text-qa-muted">сумма не объявлена</span>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : !isLoading ? (
        <Quiet>По бумагам портфеля в ближайшие 12 месяцев выплат не объявлено.</Quiet>
      ) : null}
      <a className="inline-block text-xs text-terminal-accent hover:underline" href="/api/v1/portfolio/paper/cashflows.ics" data-testid="payout-ics">
        Добавить выплаты в календарь (.ics)
      </a>
    </Block>
  );
}

/* ── Налоги ── */

type TaxRow = { ticker?: string; lth_free_from?: string | null; tax_if_sell_today?: string | number | null; tax_if_sell_after_lth?: string | number | null };

export function TaxBlock() {
  const { mode } = useProductContext();
  const { data, isLoading } = useQuery({ queryKey: ["pf-tax", mode], queryFn: () => portfolioApi.tax(mode) });
  const year = (data?.year ?? {}) as { tax_cash?: string | number | null; status?: string };
  const lth = (data?.lth ?? []) as TaxRow[];
  const harvest = (data?.loss_harvest ?? []) as Array<{ ticker?: string; tax_cash_reduction?: string | number | null }>;
  return (
    <Block
      title="Налоги"
      hint="Оценка НДФЛ по вашим сделкам и что изменится, если продать сейчас или после льготы долгосрочного владения. Учебный расчёт, не налоговая консультация; методика не подтверждена юристом."
      method="/methodology/tax"
      testId="k3-tax"
    >
      {isLoading ? <Quiet>Загрузка…</Quiet> : null}
      <StatGrid>
        <Stat label="НДФЛ за год (оценка)" value={rub(year.tax_cash) ?? DASH} />
        <Stat
          label="Можно сэкономить до 31.12"
          value={rub(harvest.reduce((a, h) => a + (Number(h.tax_cash_reduction) || 0), 0) || null) ?? DASH}
          tone={harvest.length ? "up" : "neutral"}
          sub="зафиксировав бумажный убыток"
        />
      </StatGrid>
      {lth.length ? (
        <table className="w-full text-xs" data-testid="k3-lth">
          <thead>
            <tr className="text-qa-muted text-left border-b border-cockpit-border">
              <th className="py-1.5 font-normal">Бумага</th>
              <th className="font-normal">Льгота с</th>
              <th className="font-normal text-right">Налог, если продать сегодня</th>
              <th className="font-normal text-right">После даты льготы</th>
            </tr>
          </thead>
          <tbody>
            {lth.map((r) => (
              <tr key={`${r.ticker}-${r.lth_free_from}`} className="border-b border-cockpit-border/50">
                <td className="py-1.5 font-medium">{r.ticker}</td>
                <td className="tabular-nums">{r.lth_free_from ?? DASH}</td>
                <td className="text-right tabular-nums">{rub(r.tax_if_sell_today) ?? DASH}</td>
                <td className="text-right tabular-nums text-terminal-up">{rub(r.tax_if_sell_after_lth) ?? DASH}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : !isLoading ? (
        <Quiet>Пока нет позиций с прибылью, по которым налог зависит от срока владения.</Quiet>
      ) : null}
    </Block>
  );
}

/* ── Расходы ── */

const COST_LINE: Record<string, string> = {
  broker: "Комиссии брокера",
  fund_ter: "Расходы фондов",
  spread: "Спред при сделках",
  tax: "Уплаченные налоги",
};

export function CostsBlock() {
  const { mode } = useProductContext();
  const { data, isLoading } = useQuery({ queryKey: ["pf-costs", mode], queryFn: () => accountApi.costs(mode) });
  const lines = ((data?.lines ?? []) as Array<{ id: string; rubles?: string | null }>).filter((l) => l.rubles != null);
  return (
    <Block
      title="Расходы"
      hint="Сколько вы платите за владение портфелем и во что это превращается за 10 лет."
      method="/methodology"
      testId="d62-costs"
    >
      {isLoading ? <Quiet>Загрузка…</Quiet> : null}
      <StatGrid>
        <Stat label="За год" value={rub(data?.total_rubles) ?? DASH} sub={data?.total_pct ? `${pct(data.total_pct, 2)} от капитала` : undefined} />
        {data?.ten_year?.delta != null ? (
          <Stat label="За 10 лет" value={rub(data.ten_year.delta) ?? DASH} tone="down" sub="при тех же условиях" />
        ) : null}
      </StatGrid>
      {lines.length ? (
        <ul className="text-xs space-y-1">
          {lines.map((l) => (
            <li key={l.id} className="flex justify-between border-b border-cockpit-border/50 py-1">
              <span className="text-qa-muted">{COST_LINE[l.id] ?? l.id}</span>
              <span className="tabular-nums">{rub(l.rubles, 2)}</span>
            </li>
          ))}
        </ul>
      ) : null}
    </Block>
  );
}

/* ── Цена решений ── */

export function DecisionsBlock() {
  const { mode } = useProductContext();
  const { data, isLoading } = useQuery({ queryKey: ["pf-decisions", mode], queryFn: () => accountApi.decisions(mode) });
  const alts = (data?.k1?.alternatives ?? []) as Array<{ ticker?: string; name?: string; twr?: string | null }>;
  if (!isLoading && data?.total_rubles == null && data?.time_cost?.rubles == null && data?.trade_cost?.rubles == null) return null;
  return (
    <Block
      title="Цена решений"
      hint="Сколько принесли или стоили ваши решения о времени покупок и продаж — по сравнению с тем, если бы вы просто держали те же бумаги."
      method="/methodology/decision-core"
      testId="d59-report"
    >
      {isLoading ? <Quiet>Загрузка…</Quiet> : null}
      <StatGrid>
        <Stat label="Итог решений" value={rub(data?.total_rubles) ?? DASH} tone={Number(data?.total_rubles) >= 0 ? "up" : "down"} />
        <Stat label="Выбор времени" value={rub(data?.time_cost?.rubles) ?? DASH} sub={data?.time_cost?.pp != null ? `${data.time_cost.pp} п.п.` : undefined} />
        <Stat label="Сделки" value={rub(data?.trade_cost?.rubles) ?? DASH} sub="против «купил и держу»" />
      </StatGrid>
      {data?.thin ? <Quiet>Сделок пока мало — выводы станут точнее с историей.</Quiet> : null}
      {alts.length ? (
        <div className="text-xs">
          <p className="text-qa-muted mb-1">Если бы те же пополнения шли в простые альтернативы:</p>
          <ul className="grid gap-1 sm:grid-cols-2">
            {alts.map((a) => (
              <li key={String(a.ticker)} className="flex justify-between rounded border border-cockpit-border px-3 py-1.5">
                <span>{a.name || a.ticker}</span>
                <span className="tabular-nums">{pct(a.twr) ?? DASH}</span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </Block>
  );
}

/* ── Ликвидность ── */

export function LiquidityBlock() {
  const { data, isLoading } = useQuery({ queryKey: ["pf-liquidity"], queryFn: () => portfolioApi.liquidity("paper", 0.1) });
  const issues = (data?.issues ?? []) as Array<{ ticker: string; days_to_exit: number | null }>;
  if (!isLoading && data?.share_1d == null && !issues.length) return null;
  return (
    <Block
      title="Ликвидность"
      hint="Как быстро можно продать позиции, не сдвигая цену: считаем, что вы продаёте не больше 10% обычного дневного оборота."
      method="/methodology/liquidity"
      testId="liquidity-panel"
    >
      {isLoading ? <Quiet>Загрузка…</Quiet> : null}
      <StatGrid>
        <Stat label="Продать за 1 день" value={pct(data?.share_1d) ?? DASH} sub="доля портфеля" />
        <Stat label="За 5 дней" value={pct(data?.share_5d) ?? DASH} />
      </StatGrid>
      {issues.length ? (
        <table className="w-full text-xs" data-testid="liquidity-table">
          <thead>
            <tr className="text-qa-muted text-left border-b border-cockpit-border">
              <th className="py-1.5 font-normal">Бумага</th>
              <th className="font-normal text-right">Дней на выход</th>
            </tr>
          </thead>
          <tbody>
            {issues.map((r) => (
              <tr key={r.ticker} className="border-b border-cockpit-border/50">
                <td className="py-1.5 font-medium">{r.ticker}</td>
                <td className="text-right tabular-nums">{r.days_to_exit == null ? "редкие сделки" : r.days_to_exit.toFixed(1)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : !isLoading ? (
        <Quiet>Все позиции продаются за день без заметного влияния на цену.</Quiet>
      ) : null}
    </Block>
  );
}
