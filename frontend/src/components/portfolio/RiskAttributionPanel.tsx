"use client";

import { useMutation, useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useMemo, useState } from "react";
import { Plus, RotateCcw, X } from "lucide-react";
import { portfolioApi } from "@/lib/api";
import { fetchUiTexts } from "@/lib/legal-docs";
import type { UnifiedRiskSnapshot } from "@/lib/risk-engine";

type K4Texts = {
  title?: string;
  weight?: string;
  pct_vol?: string;
  pct_cvar?: string;
  enb?: string;
  enb_hint?: string;
  not_saved?: string;
  basis?: string;
  method_link?: string;
};

const fmt = (value: number | null | undefined): string =>
  value == null || !Number.isFinite(value) ? "—" : `${(value * 100).toLocaleString("ru-RU", { maximumFractionDigits: 1 })}%`;

const num = (s: string) => Number(String(s).replace(",", ".").replace(/\s/g, ""));

const CELL = "bg-cockpit-panel border border-cockpit-border rounded px-2 py-1 text-right tabular-nums w-20 focus:border-terminal-accent focus:outline-none";

/**
 * Where portfolio risk comes from, and a sandbox to change it. The table is filled
 * from the current portfolio automatically; any share can be edited in place, a row
 * removed or a new paper added, then «Пересчитать» shows the effect. Nothing is saved.
 */
export function RiskAttributionPanel({
  snapshot,
}: {
  snapshot?: UnifiedRiskSnapshot | null;
  userId?: string;
}) {
  const { data: texts } = useQuery({
    queryKey: ["legal-ui-texts-k4"],
    queryFn: async () => {
      try {
        const data = (await fetchUiTexts()) as { k4?: K4Texts };
        return data.k4 ?? {};
      } catch {
        return {};
      }
    },
    staleTime: 60_000,
  });
  const t = texts ?? {};

  const base = useMemo(
    () => snapshot?.attribution?.components ?? snapshot?.components ?? [],
    [snapshot],
  );
  const [weights, setWeights] = useState<Record<string, string>>({});
  const [removed, setRemoved] = useState<Set<string>>(new Set());
  const [added, setAdded] = useState<Array<{ ticker: string; amount: string }>>([]);
  // «Влияние на портфель» from a ticker elsewhere arrives as ?add=TICKER.
  const [newTicker, setNewTicker] = useState(() =>
    typeof window === "undefined" ? "" : (new URLSearchParams(window.location.search).get("add") || "").toUpperCase(),
  );
  const [newAmount, setNewAmount] = useState("");
  const [cash, setCash] = useState("");
  const [preview, setPreview] = useState<UnifiedRiskSnapshot | null>(null);

  const reset = () => {
    setWeights({});
    setRemoved(new Set());
    setAdded([]);
    setCash("");
    setPreview(null);
  };
  // Shares are filled from the live portfolio; only the ones the user edits are kept in state.
  const shown = (ticker: string, weight?: number | null) => weights[ticker] ?? String(+((weight ?? 0) * 100).toFixed(1));

  const changedWeights = useMemo(() => {
    const out: Record<string, number> = {};
    for (const r of base) {
      if (removed.has(r.ticker)) continue;
      if (weights[r.ticker] == null) continue;
      const v = num(weights[r.ticker]);
      if (Number.isFinite(v) && Math.abs(v / 100 - (r.weight ?? 0)) > 0.0005) out[r.ticker] = v / 100;
    }
    return out;
  }, [base, removed, weights]);
  const dirty = Object.keys(changedWeights).length > 0 || removed.size > 0 || added.length > 0 || num(cash) > 0;
  const lockedSum = Object.values(changedWeights).reduce((a, b) => a + b, 0);

  const mutation = useMutation({
    mutationFn: () =>
      portfolioApi.riskWhatIf({
        mode: "paper",
        remove: removed.size ? [...removed] : undefined,
        set_weight: Object.keys(changedWeights).length ? changedWeights : undefined,
        add: added.length ? added.map((a) => ({ ticker: a.ticker, qty: "1", price: String(num(a.amount)), ccy: "RUB" })) : undefined,
        add_cash_rub: num(cash) > 0 ? num(cash) : undefined,
      }),
    onSuccess: setPreview,
  });

  const result = preview?.attribution?.components ?? preview?.components ?? null;
  const resultBy = new Map((result ?? []).map((r) => [r.ticker, r]));
  const enbNow = snapshot?.attribution?.enb;
  const enbNew = preview?.attribution?.enb;
  const status = snapshot?.attribution?.data_status;

  const addRow = () => {
    const ticker = newTicker.trim().toUpperCase();
    if (!ticker || !(num(newAmount) > 0)) return;
    setAdded((rows) => [...rows.filter((r) => r.ticker !== ticker), { ticker, amount: newAmount }]);
    setNewTicker("");
    setNewAmount("");
  };

  return (
    <section className="card p-5 space-y-4" data-testid="k4-attribution">
      <header className="flex items-start justify-between gap-3">
        <div>
          <h2 className="text-sm font-semibold">{t.title || "Откуда риск портфеля"}</h2>
          <p className="text-xs text-qa-muted mt-1 max-w-2xl">
            Доли заполнены по вашему портфелю. Поменяйте любую, уберите бумагу или добавьте новую — и нажмите «Пересчитать»,
            чтобы увидеть, как изменится риск.
          </p>
        </div>
        <Link href="/methodology" className="shrink-0 text-[11px] text-qa-muted hover:text-terminal-accent hover:underline">
          {t.method_link || "Как считается"}
        </Link>
      </header>

      {status === "частично" || snapshot?.attribution?.partial ? (
        <p className="text-xs text-terminal-accent" data-testid="k4-partial">
          Часть бумаг без истории цен — они не вошли в расчёт{snapshot?.attribution?.reason ? `: ${snapshot.attribution.reason}` : ""}.
        </p>
      ) : null}

      {!base.length ? (
        <p className="text-sm text-qa-muted">{(snapshot as { reason?: string } | null | undefined)?.reason === "пустая книга" ? "Как только в портфеле появятся позиции, здесь будет видно, какая из них даёт больше риска." : "По бумагам портфеля пока не хватает истории цен, чтобы разложить риск. Расчёт появится автоматически, когда подтянутся котировки."}</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-xs" data-testid="k4-table">
            <thead>
              <tr className="text-qa-muted text-left border-b border-cockpit-border">
                <th className="py-1.5 font-normal">Бумага</th>
                <th className="font-normal text-right">{t.weight || "Доля в портфеле"}</th>
                <th className="font-normal text-right">{t.pct_vol || "Доля в колебаниях"}</th>
                <th className="font-normal text-right">{t.pct_cvar || "Доля в потерях худших дней"}</th>
                <th className="w-8" aria-label="Убрать" />
              </tr>
            </thead>
            <tbody>
              {base.map((row) => {
                const gone = removed.has(row.ticker);
                const after = resultBy.get(row.ticker);
                return (
                  <tr key={row.ticker} className={`border-b border-cockpit-border/50 ${gone ? "opacity-40 line-through" : ""}`}>
                    <td className="py-1.5 font-medium">{row.ticker}</td>
                    <td className="text-right">
                      <label className="inline-flex items-center gap-1">
                        <span className="sr-only">Доля {row.ticker}, %</span>
                        <input
                          className={CELL}
                          inputMode="decimal"
                          disabled={gone}
                          value={shown(row.ticker, row.weight)}
                          onChange={(e) => setWeights((w) => ({ ...w, [row.ticker]: e.target.value }))}
                          data-testid={`k4-w-${row.ticker}`}
                        />
                        <span className="text-qa-muted">%</span>
                      </label>
                    </td>
                    <td className="text-right tabular-nums" data-testid={`k4-vol-${row.ticker}`}>
                      {fmt(row.pct_of_vol)}
                      {preview && !gone ? <span className="block text-terminal-accent">→ {fmt(after?.pct_of_vol)}</span> : null}
                    </td>
                    <td className="text-right tabular-nums">
                      {fmt(row.pct_of_cvar)}
                      {preview && !gone ? <span className="block text-terminal-accent">→ {fmt(after?.pct_of_cvar)}</span> : null}
                    </td>
                    <td className="text-right">
                      <button
                        type="button"
                        className="p-1 text-qa-muted hover:text-terminal-down"
                        aria-label={gone ? `Вернуть ${row.ticker}` : `Убрать ${row.ticker}`}
                        title={gone ? "Вернуть" : "Убрать из расчёта"}
                        onClick={() =>
                          setRemoved((s) => {
                            const n = new Set(s);
                            if (n.has(row.ticker)) n.delete(row.ticker);
                            else n.add(row.ticker);
                            return n;
                          })
                        }
                        data-testid={`k4-drop-${row.ticker}`}
                      >
                        {gone ? <RotateCcw size={13} /> : <X size={13} />}
                      </button>
                    </td>
                  </tr>
                );
              })}
              {added.map((a) => {
                const after = resultBy.get(a.ticker);
                return (
                  <tr key={`add-${a.ticker}`} className="border-b border-cockpit-border/50 text-terminal-accent">
                    <td className="py-1.5 font-medium">+ {a.ticker}</td>
                    <td className="text-right tabular-nums">{Number(num(a.amount)).toLocaleString("ru-RU")} ₽</td>
                    <td className="text-right tabular-nums">{preview ? fmt(after?.pct_of_vol) : "—"}</td>
                    <td className="text-right tabular-nums">{preview ? fmt(after?.pct_of_cvar) : "—"}</td>
                    <td className="text-right">
                      <button
                        type="button"
                        className="p-1 text-qa-muted hover:text-terminal-down"
                        aria-label={`Убрать ${a.ticker}`}
                        onClick={() => setAdded((rows) => rows.filter((r) => r.ticker !== a.ticker))}
                      >
                        <X size={13} />
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {base.length ? (
        <div className="flex flex-wrap items-end gap-3 text-xs">
          <label className="flex flex-col gap-1">
            <span className="text-qa-muted">Добавить бумагу</span>
            <input
              className="bg-cockpit-panel border border-cockpit-border rounded px-2 py-1 w-28 uppercase"
              placeholder="тикер, напр. SBER"
              value={newTicker}
              onChange={(e) => setNewTicker(e.target.value)}
              data-testid="k4-add-ticker"
            />
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-qa-muted">на сумму, ₽</span>
            <input className={CELL + " w-28"} inputMode="numeric" value={newAmount} onChange={(e) => setNewAmount(e.target.value)} data-testid="k4-add-amount" />
          </label>
          <button type="button" className="btn-ghost text-xs inline-flex items-center gap-1" onClick={addRow} disabled={!newTicker.trim() || !(num(newAmount) > 0)}>
            <Plus size={12} /> Добавить
          </button>
          <label className="flex flex-col gap-1 ml-auto">
            <span className="text-qa-muted">Довнести деньги, ₽</span>
            <input className={CELL + " w-28"} inputMode="numeric" value={cash} onChange={(e) => setCash(e.target.value)} data-testid="k4-cash" />
          </label>
        </div>
      ) : null}

      {lockedSum > 1.0001 ? (
        <p className="text-xs text-terminal-down">Изменённые доли в сумме больше 100% — уменьшите какую-нибудь.</p>
      ) : null}

      {base.length ? (
        <div className="flex flex-wrap items-center gap-3">
          <button
            type="button"
            className="btn-primary text-xs"
            onClick={() => mutation.mutate()}
            disabled={!dirty || mutation.isPending || lockedSum > 1.0001}
            data-testid="k4-recalc"
          >
            {mutation.isPending ? "Считаем…" : "Пересчитать"}
          </button>
          {dirty || preview ? (
            <button type="button" className="btn-ghost text-xs inline-flex items-center gap-1" onClick={reset}>
              <RotateCcw size={12} /> Вернуть как в портфеле
            </button>
          ) : null}
          <span className="text-xs" data-testid="k4-enb">
            {t.enb || "Независимых источников риска"}:{" "}
            <b className="tabular-nums">{enbNow == null || !Number.isFinite(enbNow) ? "—" : enbNow.toFixed(1)}</b>
            {preview && enbNew != null && Number.isFinite(enbNew) ? (
              <b className="tabular-nums text-terminal-accent"> → {enbNew.toFixed(1)}</b>
            ) : null}
            <span className="text-qa-muted"> из {base.length}</span>
          </span>
        </div>
      ) : null}
      {t.enb_hint && base.length ? <p className="text-[11px] text-qa-muted">{t.enb_hint}</p> : null}
      {mutation.isError ? (
        <p className="text-xs text-terminal-down" data-testid="k4-error">
          Не удалось пересчитать. Проверьте тикер новой бумаги и попробуйте ещё раз.
        </p>
      ) : null}
      <p className="text-[11px] text-qa-muted" data-testid="k4-not-saved">
        {t.not_saved || "Расчёт не меняет ваш портфель и не сохраняется."} {t.basis}
      </p>
    </section>
  );
}
