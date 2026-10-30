"use client";

import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { clsx } from "clsx";
import { AlertTriangle, ShieldCheck } from "lucide-react";
import { futuresApi, type FuturesContract, type FuturesDesk as Desk } from "@/lib/api";
import { useProductContext } from "@/contexts/ProductContext";
import { Block, DASH, Quiet, Stat, StatGrid, pct, rub } from "@/components/portfolio/ui";

const GROUPS: Array<{ id: FuturesContract["group"]; title: string }> = [
  { id: "index", title: "Индексы" },
  { id: "fx", title: "Валюта" },
  { id: "commodity", title: "Сырьё и металлы" },
  { id: "stock", title: "Акции" },
];

const INPUT =
  "w-full rounded-md border border-cockpit-border bg-cockpit-panel px-2.5 py-1.5 text-sm tabular-nums text-qa-text focus:border-terminal-accent focus:outline-none";

const num = (v: string) => Number(String(v).replace(",", ".").replace(/\s/g, ""));
const fmt = (v: number | null | undefined, d = 2) =>
  v == null || !Number.isFinite(v) ? DASH : v.toLocaleString("ru-RU", { maximumFractionDigits: d, minimumFractionDigits: 0 });
const signed = (v: number | null | undefined) => (v == null ? DASH : `${v > 0 ? "+" : ""}${rub(v) ?? DASH}`);
const tone = (v: number | null | undefined) => (v == null ? "" : v >= 0 ? "text-terminal-up" : "text-terminal-down");

function plural(n: number, one: string, few: string, many: string) {
  const m10 = n % 10;
  const m100 = n % 100;
  const w = m10 === 1 && m100 !== 11 ? one : m10 >= 2 && m10 <= 4 && (m100 < 12 || m100 > 14) ? few : many;
  return `${n} ${w}`;
}

function expiryText(c: Pick<FuturesContract, "perpetual" | "expiry" | "days_to_expiry">) {
  if (c.perpetual) return "без даты исполнения";
  if (!c.expiry) return DASH;
  return `${new Date(c.expiry).toLocaleDateString("ru-RU", { day: "numeric", month: "long", year: "numeric" })} (через ${plural(c.days_to_expiry ?? 0, "день", "дня", "дней")})`;
}

/* ── 1. My futures + margin cushion ───────────────────────────────────────── */

function MyFutures({ desk }: { desk: Desk }) {
  const pos = desk.positions;
  const [cash, setCash] = useState(desk.cash_rub != null ? String(Math.round(desk.cash_rub)) : "");
  const [minPct, setMinPct] = useState("50");
  const required = pos.reduce((a, p) => a + p.margin, 0);
  const exposure = pos.reduce((a, p) => a + p.notional, 0);
  const minimum = (required * num(minPct)) / 100;
  const free = num(cash) - required;
  const cushion = Math.abs(exposure) > 0 && num(cash) > 0 ? (num(cash) - minimum) / Math.abs(exposure) : null;
  const dayVar = pos.reduce((a, p) => a + (p.variation_today ?? 0), 0);

  if (!pos.length) {
    return (
      <Block title="Мои фьючерсы" testId="fut-mine">
        <Quiet>
          Фьючерсов в портфеле нет. Ниже — сколько стоит контракт, какое обеспечение он требует и как фьючерсом защитить
          портфель акций от падения рынка или от изменения курса.
        </Quiet>
      </Block>
    );
  }
  return (
    <Block
      title="Мои фьючерсы"
      hint="Вариационная маржа — сколько биржа сегодня списала или зачислила по позиции. Обеспечение (ГО) — сколько денег заблокировано под контракты."
      method="/methodology/futures"
      testId="fut-mine"
    >
      <StatGrid>
        <Stat label="Обеспечение (ГО)" value={rub(required) ?? DASH} />
        <Stat label="Позиция по рынку" value={rub(Math.abs(exposure)) ?? DASH} sub={exposure >= 0 ? "в длинную сторону" : "в короткую сторону"} />
        <Stat label="Вариационная маржа сегодня" value={signed(dayVar)} tone={dayVar >= 0 ? "up" : "down"} />
        <Stat
          label="Запас до требования довнести"
          value={cushion == null ? DASH : pct(Math.max(0, cushion))}
          tone={cushion == null ? "neutral" : cushion < 0.05 ? "down" : cushion < 0.15 ? "accent" : "up"}
          sub="движение рынка против позиции"
        />
      </StatGrid>
      <div className="overflow-x-auto">
        <table className="w-full text-xs" data-testid="fut-mine-table">
          <thead>
            <tr className="text-qa-muted text-left border-b border-cockpit-border">
              <th className="py-1.5 font-normal">Контракт</th>
              <th className="font-normal text-right">Контрактов</th>
              <th className="font-normal text-right">Цена</th>
              <th className="font-normal text-right">ГО</th>
              <th className="font-normal text-right">За сегодня</th>
              <th className="font-normal text-right">С момента входа</th>
              <th className="font-normal text-right">Исполнение</th>
            </tr>
          </thead>
          <tbody>
            {pos.map((p) => (
              <tr key={p.secid} className="border-b border-cockpit-border/50">
                <td className="py-1.5">
                  <span className="font-medium">{p.secid}</span> <span className="text-qa-muted">{p.title}</span>
                </td>
                <td className={clsx("text-right tabular-nums", p.qty < 0 && "text-terminal-down")}>{p.qty > 0 ? `+${p.qty}` : p.qty}</td>
                <td className="text-right tabular-nums">{fmt(p.price)}</td>
                <td className="text-right tabular-nums">{rub(p.margin) ?? DASH}</td>
                <td className={clsx("text-right tabular-nums", tone(p.variation_today))}>{signed(p.variation_today)}</td>
                <td className={clsx("text-right tabular-nums", tone(p.pnl_since_entry))}>{signed(p.pnl_since_entry)}</td>
                <td className="text-right">
                  {expiryText(p)}
                  {p.roll_soon ? (
                    <span className="block text-terminal-accent">перенесите в {p.next_secid ?? "следующий контракт"}</span>
                  ) : null}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="grid gap-3 sm:grid-cols-3 text-xs items-end">
        <label className="space-y-1">
          <span className="text-qa-muted">Деньги на счёте под обеспечение, ₽</span>
          <input className={INPUT} inputMode="numeric" value={cash} onChange={(e) => setCash(e.target.value)} data-testid="fut-cash" />
        </label>
        <label className="space-y-1">
          <span className="text-qa-muted">Брокер требует держать не меньше, % от ГО</span>
          <input className={INPUT} inputMode="numeric" value={minPct} onChange={(e) => setMinPct(e.target.value)} />
        </label>
        <p className="text-qa-muted pb-1.5">
          {num(cash) > 0 ? (
            free < 0 ? (
              <span className="text-terminal-down">Денег меньше, чем требует обеспечение: не хватает {rub(-free)}.</span>
            ) : (
              <>Свободно сверх обеспечения: <b className="text-qa-text">{rub(free)}</b>.</>
            )
          ) : (
            "Укажите деньги на счёте — посчитаем запас."
          )}
        </p>
      </div>
      {cushion != null ? (
        <p className="text-xs" data-testid="fut-cushion">
          Если рынок пойдёт против позиции примерно на <b>{pct(Math.max(0, cushion))}</b>, деньги на счёте опустятся до
          минимума брокера ({rub(minimum)}) — брокер попросит довнести деньги или начнёт закрывать позиции.
        </p>
      ) : null}
    </Block>
  );
}

/* ── 2. Hedge the stock portfolio ─────────────────────────────────────────── */

function Hedge({ desk }: { desk: Desk }) {
  const h = desk.hedge;
  const candidates = desk.contracts.filter((c) => c.hedge === "equity" && c.contract_value);
  const [secid, setSecid] = useState(candidates.find((c) => c.asset === "MIX")?.secid ?? candidates[0]?.secid ?? "");
  const [share, setShare] = useState(100);
  const c = candidates.find((x) => x.secid === secid);
  const V = h.equity_value_rub ?? 0;
  const beta = h.beta ?? 0;
  const ready = V > 0 && beta > 0 && c?.contract_value;

  const calc = useMemo(() => {
    if (!ready || !c?.contract_value) return null;
    const exact = (beta * V * (share / 100)) / c.contract_value;
    // Round to whole contracts, but never protect more than asked (over-hedging turns a hedge into a bet).
    const n = Math.max(0, Math.round(exact) > exact + 1e-9 && share >= 100 ? Math.floor(exact) : Math.round(exact));
    const coverage = (n * c.contract_value) / (beta * V);
    const margin = n * (c.initial_margin ?? 0);
    const fees = n * (c.fee ?? 0) * 2;
    const scen = [-0.2, -0.1, 0.1].map((m) => {
      const port = beta * V * m;
      const fut = -n * c.contract_value! * m;
      return { m, port, fut, total: port + fut };
    });
    let volAfter: number | null = null;
    if (h.portfolio_vol != null && h.index_vol != null) {
      const sys = beta * beta * h.index_vol * h.index_vol;
      volAfter = Math.sqrt(Math.max(0, h.portfolio_vol * h.portfolio_vol - sys * (2 * coverage - coverage * coverage)));
    }
    return { exact, n, coverage, margin, fees, scen, volAfter };
  }, [ready, c, beta, V, share, h.portfolio_vol, h.index_vol]);

  return (
    <Block
      title="Защитить портфель от падения рынка"
      hint="Продажа фьючерса на индекс Мосбиржи частично компенсирует падение акций: если рынок падает, фьючерс приносит деньги. Бумаги продавать не нужно, налога нет. Расчёт для понимания, не рекомендация."
      method="/methodology/futures"
      testId="k58a-panel"
    >
      {!V ? (
        <Quiet>
          В портфеле нет российских акций с историей цен — защищать нечего. {h.skipped?.length ? `Нет истории по: ${h.skipped.join(", ")}.` : ""}
        </Quiet>
      ) : (
        <>
          <StatGrid>
            <Stat label="Акции в портфеле" value={rub(V) ?? DASH} />
            <Stat label="Бета к индексу" value={h.beta == null ? DASH : h.beta.toFixed(2)} sub="1 — двигаются как индекс" />
            <Stat label="Волатильность портфеля" value={pct(h.portfolio_vol)} sub="за год" />
            <Stat label="Волатильность индекса" value={pct(h.index_vol)} sub="за год" />
          </StatGrid>
          <div className="flex flex-wrap items-center gap-2 text-xs">
            <span className="text-qa-muted">Чем защищать:</span>
            {candidates.map((x) => (
              <button
                key={x.secid}
                type="button"
                onClick={() => setSecid(x.secid)}
                className={clsx(
                  "rounded-full border px-3 py-1",
                  x.secid === secid ? "border-terminal-accent bg-terminal-accent text-black font-semibold" : "border-cockpit-border hover:border-terminal-accent",
                )}
              >
                {x.title} · {x.secid}
              </button>
            ))}
          </div>
          <label className="flex flex-wrap items-center gap-3 text-xs" htmlFor="k58a-share">
            <span className="font-medium">Какую часть рыночного риска снять</span>
            <input
              id="k58a-share"
              type="range"
              min={0}
              max={100}
              step={5}
              value={share}
              onChange={(e) => setShare(Number(e.target.value))}
              className="w-56 accent-[var(--qa-accent)]"
              data-testid="k58a-share"
            />
            <span className="tabular-nums font-semibold text-terminal-accent">{share}%</span>
          </label>
          {calc && c ? (
            <>
              <StatGrid>
                <Stat label="Продать контрактов" value={<span data-testid="k58a-hedge">{calc.n}</span>} tone="accent" sub={`точно ${fmt(calc.exact, 2)} · ${c.secid}`} />
                <Stat label="Обеспечение (ГО)" value={rub(calc.margin) ?? DASH} sub="заблокируется на счёте" />
                <Stat label="Защищено на самом деле" value={pct(calc.coverage, 0)} sub="контракты целые, поэтому не ровно" />
                <Stat label="Волатильность после" value={pct(calc.volAfter)} sub={h.portfolio_vol != null ? `было ${pct(h.portfolio_vol)}` : undefined} tone="up" />
              </StatGrid>
              <table className="w-full text-xs" data-testid="fut-hedge-scenarios">
                <thead>
                  <tr className="text-qa-muted text-left border-b border-cockpit-border">
                    <th className="py-1.5 font-normal">Если индекс</th>
                    <th className="font-normal text-right">Акции</th>
                    <th className="font-normal text-right">Фьючерсы</th>
                    <th className="font-normal text-right">Итого</th>
                  </tr>
                </thead>
                <tbody>
                  {calc.scen.map((s) => (
                    <tr key={s.m} className="border-b border-cockpit-border/50">
                      <td className="py-1.5">{s.m > 0 ? "вырастет" : "упадёт"} на {Math.abs(s.m * 100)}%</td>
                      <td className={clsx("text-right tabular-nums", tone(s.port))}>{signed(s.port)}</td>
                      <td className={clsx("text-right tabular-nums", tone(s.fut))}>{signed(s.fut)}</td>
                      <td className={clsx("text-right tabular-nums font-semibold", tone(s.total))}>{signed(s.total)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <ul className="text-xs text-qa-muted space-y-1 list-disc pl-4">
                <li>
                  {c.perpetual
                    ? "Вечный контракт не нужно переносить, но раз в день по нему начисляется плата за перенос — она может быть и в плюс, и в минус."
                    : `Контракт исполняется ${expiryText(c)}. Чтобы защита не пропала, его нужно заранее перенести в следующий${c.next_secid ? ` (${c.next_secid})` : ""}.`}
                </li>
                <li>Защита убирает и рост: если рынок вырастет, фьючерсы дадут убыток, который съест часть прибыли акций.</li>
                <li>Комиссия биржи за вход и выход ≈ {rub(calc.fees, 2) ?? DASH}, плюс комиссия брокера.</li>
                <li>Бета считается по прошлому году; в кризис связь с индексом может меняться.</li>
              </ul>
            </>
          ) : (
            <Quiet>Нет цены контракта — расчёт появится, когда биржа ответит.</Quiet>
          )}
        </>
      )}
    </Block>
  );
}

function FxHedge({ desk }: { desk: Desk }) {
  const fx = desk.hedge.fx_exposure_rub ?? {};
  const rows = Object.entries(fx)
    .map(([ccy, value]) => {
      const contract = desk.contracts.find((c) => c.hedge === ccy && !c.perpetual) ?? desk.contracts.find((c) => c.hedge === ccy);
      const n = contract?.contract_value ? value / contract.contract_value : null;
      return { ccy, value, contract, n };
    })
    .filter((r) => r.value > 0);
  if (!rows.length) return null;
  return (
    <Block
      title="Защитить от изменения курса"
      hint="Если часть портфеля в валюте, укрепление рубля уменьшает её стоимость. Продажа валютного фьючерса фиксирует курс."
      testId="fut-fx"
    >
      <table className="w-full text-xs">
        <thead>
          <tr className="text-qa-muted text-left border-b border-cockpit-border">
            <th className="py-1.5 font-normal">Валюта</th>
            <th className="font-normal text-right">Стоимость в рублях</th>
            <th className="font-normal">Контракт</th>
            <th className="font-normal text-right">Продать контрактов</th>
            <th className="font-normal text-right">ГО</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.ccy} className="border-b border-cockpit-border/50">
              <td className="py-1.5 font-medium">{r.ccy}</td>
              <td className="text-right tabular-nums">{rub(r.value)}</td>
              <td>{r.contract ? `${r.contract.secid} · ${r.contract.title}` : "нет контракта"}</td>
              <td className="text-right tabular-nums">{r.n == null ? DASH : `${Math.round(r.n)} (точно ${fmt(r.n, 2)})`}</td>
              <td className="text-right tabular-nums">
                {r.n == null || !r.contract?.initial_margin ? DASH : rub(Math.round(r.n) * r.contract.initial_margin)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </Block>
  );
}

/* ── 3. Contract calculator ───────────────────────────────────────────────── */

function Calculator({ desk }: { desk: Desk }) {
  const [q, setQ] = useState("");
  const [secid, setSecid] = useState(desk.contracts[0]?.secid ?? "");
  const [qty, setQty] = useState("1");
  const [side, setSide] = useState<"long" | "short">("long");
  const found = useQuery({
    queryKey: ["fut-search", q],
    queryFn: () => futuresApi.contracts(q),
    enabled: q.trim().length >= 2,
    staleTime: 60_000,
  });
  const pool = useMemo(() => {
    const m = new Map<string, FuturesContract>();
    for (const c of [...desk.contracts, ...(found.data ?? [])]) m.set(c.secid, c);
    return m;
  }, [desk.contracts, found.data]);
  const c = pool.get(secid);
  const n = Math.max(0, num(qty) || 0);
  const value = (c?.contract_value ?? 0) * n;
  const margin = (c?.initial_margin ?? 0) * n;
  const onePct = value * 0.01;
  const sign = side === "long" ? 1 : -1;

  return (
    <Block title="Калькулятор контракта" hint="Сколько денег нужно, чтобы открыть позицию, и сколько она приносит или теряет при движении цены." testId="fut-calc">
      <div className="grid gap-3 sm:grid-cols-4 items-end text-xs">
        <label className="space-y-1 sm:col-span-2">
          <span className="text-qa-muted">Контракт</span>
          <select className={INPUT} value={secid} onChange={(e) => setSecid(e.target.value)} data-testid="fut-calc-contract">
            {[...pool.values()].map((x) => (
              <option key={x.secid} value={x.secid}>
                {x.secid} — {x.title}
              </option>
            ))}
          </select>
        </label>
        <label className="space-y-1">
          <span className="text-qa-muted">Найти другой</span>
          <input className={INPUT} placeholder="код или название" value={q} onChange={(e) => setQ(e.target.value)} />
        </label>
        <label className="space-y-1">
          <span className="text-qa-muted">Сколько контрактов</span>
          <input className={INPUT} inputMode="numeric" value={qty} onChange={(e) => setQty(e.target.value)} data-testid="fut-calc-qty" />
        </label>
      </div>
      {q.trim().length >= 2 && found.data?.length ? (
        <div className="flex flex-wrap gap-1.5">
          {found.data.slice(0, 8).map((x) => (
            <button key={x.secid} type="button" className="rounded-full border border-cockpit-border px-2.5 py-0.5 text-[11px] hover:border-terminal-accent" onClick={() => setSecid(x.secid)}>
              {x.secid} · {x.title}
            </button>
          ))}
        </div>
      ) : null}
      <div className="flex gap-2 text-xs">
        {(["long", "short"] as const).map((s) => (
          <button
            key={s}
            type="button"
            onClick={() => setSide(s)}
            className={clsx(
              "rounded-md border px-3 py-1",
              side === s ? (s === "long" ? "border-terminal-up text-terminal-up" : "border-terminal-down text-terminal-down") : "border-cockpit-border text-qa-muted",
            )}
          >
            {s === "long" ? "Купить (заработать на росте)" : "Продать (заработать на падении)"}
          </button>
        ))}
      </div>
      {c ? (
        <>
          <StatGrid>
            <Stat label="Нужно на счёте (ГО)" value={rub(margin) ?? DASH} sub={`${rub(c.initial_margin) ?? DASH} за контракт`} />
            <Stat label="Позиция по рынку" value={rub(value) ?? DASH} sub={c.leverage ? `плечо ×${fmt(c.leverage, 1)}` : undefined} />
            <Stat label="Рынок +1%" value={signed(sign * onePct)} tone={sign > 0 ? "up" : "down"} />
            <Stat label="Рынок −1%" value={signed(-sign * onePct)} tone={sign > 0 ? "down" : "up"} />
          </StatGrid>
          <p className="text-xs text-qa-muted">
            Шаг цены {fmt(c.tick, 6)} = {rub(c.tick_value, 2) ?? DASH} за контракт · исполнение: {expiryText(c)} · биржевой сбор ≈ {rub((c.fee ?? 0) * n, 2) ?? DASH}.
            {c.leverage && c.leverage > 5 ? (
              <span className="text-terminal-accent"> Движение цены на {pct(1 / c.leverage, 0)} против позиции съедает всё обеспечение.</span>
            ) : null}
          </p>
        </>
      ) : null}
    </Block>
  );
}

/* ── 4. Reference ─────────────────────────────────────────────────────────── */

function Reference({ desk }: { desk: Desk }) {
  return (
    <Block
      title="Ходовые контракты"
      hint="Ближайший контракт по каждому активу. Плечо — во сколько раз позиция больше обеспечения."
      testId="fut-reference"
    >
      {GROUPS.map((g) => {
        const rows = desk.contracts.filter((c) => c.group === g.id);
        if (!rows.length) return null;
        return (
          <div key={g.id} className="space-y-1">
            <p className="text-[11px] uppercase tracking-wide text-qa-muted">{g.title}</p>
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead>
                  <tr className="text-qa-muted text-left border-b border-cockpit-border">
                    <th className="py-1.5 font-normal">Актив</th>
                    <th className="font-normal">Код</th>
                    <th className="font-normal text-right">Цена</th>
                    <th className="font-normal text-right">За день</th>
                    <th className="font-normal text-right">Контракт стоит</th>
                    <th className="font-normal text-right">ГО</th>
                    <th className="font-normal text-right">Плечо</th>
                    <th className="font-normal text-right">Исполнение</th>
                    <th className="font-normal text-right">Открытых позиций</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((c) => (
                    <tr key={c.secid} className="border-b border-cockpit-border/50">
                      <td className="py-1.5">{c.title}</td>
                      <td className="font-medium">{c.secid}</td>
                      <td className="text-right tabular-nums">{fmt(c.price, 4)}</td>
                      <td className={clsx("text-right tabular-nums", tone(c.change))}>{c.change == null ? DASH : `${c.change > 0 ? "+" : ""}${pct(c.change, 2)}`}</td>
                      <td className="text-right tabular-nums">{rub(c.contract_value) ?? DASH}</td>
                      <td className="text-right tabular-nums">{rub(c.initial_margin) ?? DASH}</td>
                      <td className="text-right tabular-nums">{c.leverage ? `×${fmt(c.leverage, 1)}` : DASH}</td>
                      <td className="text-right">{expiryText(c)}</td>
                      <td className="text-right tabular-nums">{fmt(c.open_interest, 0)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        );
      })}
    </Block>
  );
}

export function FuturesDeskView() {
  const { mode } = useProductContext();
  const { data, isLoading, isError } = useQuery({
    queryKey: ["futures-desk", mode],
    queryFn: () => futuresApi.desk(mode),
    refetchInterval: 60_000,
  });
  if (isLoading) return <Quiet>Загружаем данные срочного рынка…</Quiet>;
  if (isError || !data) {
    return (
      <div className="card p-5 text-sm flex items-center gap-2">
        <AlertTriangle size={16} className="text-terminal-down" /> Биржа не ответила. Попробуйте обновить страницу через минуту.
      </div>
    );
  }
  return (
    <div className="space-y-5">
      <p className="text-xs text-qa-muted flex items-center gap-1.5">
        <ShieldCheck size={13} aria-hidden />
        {data.source}
        {data.freshness === "closed" ? " · по итогам последних торгов" : data.delayed ? " · с задержкой 15 минут" : " · в реальном времени"} ·{" "}
        <Link href="/methodology/futures" className="underline">
          как считается
        </Link>
      </p>
      {!data.contracts.length ? <Quiet>Биржа пока не отдала список контрактов — обновим через минуту.</Quiet> : null}
      <MyFutures desk={data} />
      <Hedge desk={data} />
      <FxHedge desk={data} />
      {data.contracts.length ? <Calculator desk={data} /> : null}
      {data.contracts.length ? <Reference desk={data} /> : null}
    </div>
  );
}
