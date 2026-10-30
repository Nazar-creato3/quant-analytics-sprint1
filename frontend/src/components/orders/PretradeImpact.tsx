"use client";

import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { accountApi } from "@/lib/api";
import { useProductContext } from "@/contexts/ProductContext";
import { PRETRADE_BLOCK_LABELS } from "@/lib/actPreviewInputs";

type Side = { var_95?: number | null; hhi?: string | number | null; weights?: Record<string, string | number> };
type Out = {
  before?: Side;
  after?: Side;
  texts?: Record<string, string>;
  blocks?: Record<string, { status?: string; sentence?: string | null }>;
};

const pct = (v: unknown, d = 1) => {
  const n = Number(v);
  return v == null || !Number.isFinite(n) ? null : `${(n * 100).toLocaleString("ru-RU", { maximumFractionDigits: d })}%`;
};

function useDebounced<T>(value: T, ms: number): T {
  const [v, setV] = useState(value);
  useEffect(() => {
    const id = setTimeout(() => setV(value), ms);
    return () => clearTimeout(id);
  }, [value, ms]);
  return v;
}

/** «Как сделка изменит портфель» — recalculated as the order is typed, before anything is sent. */
export function PretradeImpact({ ticker, side, qty, price }: { ticker: string; side: "buy" | "sell"; qty: number; price: number }) {
  const { mode } = useProductContext();
  const key = useDebounced(`${ticker}|${side}|${qty}|${price}`, 700);
  const [t, s, q, p] = key.split("|");
  const ready = Number(q) > 0 && Number(p) > 0;
  const { data, isFetching } = useQuery({
    queryKey: ["pretrade-impact", key, mode],
    enabled: ready,
    staleTime: 60_000,
    queryFn: async () => (await accountApi.pretradeCheck([{ ticker: t, side: s, qty: q, price: p }], mode)) as Out,
  });
  if (!ready) return null;

  const before = data?.before;
  const after = data?.after;
  const shareNow = before?.weights?.[ticker.toUpperCase()];
  const rows: Array<{ label: string; now: string | null; then: string | null }> = [
    { label: "Доля бумаги в портфеле", now: data ? pct(shareNow ?? 0) : null, then: pct(after?.weights?.[ticker.toUpperCase()]) },
    { label: "Возможный дневной убыток (VaR 95%)", now: pct(before?.var_95, 2), then: pct(after?.var_95, 2) },
    { label: "Концентрация (HHI)", now: before?.hhi != null ? Number(before.hhi).toFixed(3) : null, then: after?.hhi != null ? Number(after.hhi).toFixed(3) : null },
  ].filter((r) => r.now != null || r.then != null);
  const sentences = Object.entries(data?.blocks ?? {})
    .filter(([, b]) => b?.sentence)
    .map(([k, b]) => ({ label: PRETRADE_BLOCK_LABELS[k] ?? k, text: String(b.sentence) }));

  return (
    <div className="mb-3 p-3 rounded border border-qa-border bg-qa-panel-secondary/50 text-xs space-y-2" data-testid="d60-pretrade">
      <div className="flex items-center justify-between gap-2">
        <p className="font-semibold text-qa-text">Как сделка изменит портфель</p>
        {isFetching ? <span className="text-[10px] text-qa-muted">считаем…</span> : null}
      </div>
      {rows.length ? (
        <table className="w-full">
          <thead>
            <tr className="text-qa-muted text-left">
              <th className="font-normal py-0.5" />
              <th className="font-normal text-right">Сейчас</th>
              <th className="font-normal text-right">После сделки</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.label}>
                <td className="py-0.5 text-qa-muted">{r.label}</td>
                <td className="text-right tabular-nums">{r.now ?? "—"}</td>
                <td className="text-right tabular-nums font-semibold">{r.then ?? "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : data ? (
        <p className="text-qa-muted">Для этой бумаги пока не хватает истории цен, чтобы оценить влияние.</p>
      ) : null}
      {sentences.length ? (
        <ul className="space-y-0.5 text-qa-muted">
          {sentences.map((x) => (
            <li key={x.label}>
              <span className="text-qa-text">{x.label}:</span> {x.text}
            </li>
          ))}
        </ul>
      ) : null}
      <p className="text-[10px] text-qa-muted">
        Расчёт не отправляет заявку. Решение принимаете вы.{" "}
        <Link href="/methodology" className="underline">
          Как считается
        </Link>
      </p>
    </div>
  );
}
