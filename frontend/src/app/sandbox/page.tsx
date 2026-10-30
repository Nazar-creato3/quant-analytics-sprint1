"use client";

import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { NavBar } from "@/components/layout/NavBar";
import { AppPageShell } from "@/components/layout/AppPageShell";
import { forecastApi } from "@/lib/api";
import { useProductContext } from "@/contexts/ProductContext";

export default function SandboxPage() {
  const { activeAccount } = useProductContext();
  const [ticker, setTicker] = useState("SBER");
  const [qty, setQty] = useState("1");
  const sim = useMutation({
    mutationFn: () => forecastApi.sandboxSimulate(activeAccount, [{ ticker, qty, price: "1", ccy: "RUB" }]),
  });

  return (
    <div className="min-h-screen bg-cockpit-bg text-qa-text flex flex-col operator-shell">
      <NavBar />
      <AppPageShell title="Песочница" description="Копия вашего портфеля: пробуйте изменения без последствий для настоящего счёта.">
        <div className="space-y-3" data-testid="sandbox-page">
          <p className="text-xs text-qa-muted">Пересчёт риска на сервере. Нет заявок и нет формулировок «купить/продать».</p>
          <label className="block text-xs text-qa-muted">
            Тикер
            <input className="mt-1 w-full rounded border border-qa-border bg-transparent px-2 py-1" value={ticker} onChange={(e) => setTicker(e.target.value)} />
          </label>
          <label className="block text-xs text-qa-muted">
            Количество в копии
            <input className="mt-1 w-full rounded border border-qa-border bg-transparent px-2 py-1" value={qty} onChange={(e) => setQty(e.target.value)} />
          </label>
          <button type="button" className="underline text-terminal-accent text-sm" data-testid="sandbox-run" onClick={() => sim.mutate()}>
            Пересчитать копию
          </button>
          {sim.isError ? <p className="text-sm text-qa-muted">нет данных · флаг выключен</p> : null}
          {sim.data ? (
            <div className="text-xs space-y-1">
              <p>VaR: {sim.data.risk?.var_95 != null ? String(sim.data.risk.var_95) : "нет данных"}</p>
              <p>HHI: {sim.data.concentration?.hhi != null ? String(sim.data.concentration.hhi) : "нет данных"}</p>
              <p>{sim.data.disclaimer}</p>
              <p>{sim.data.elapsed_ms} мс</p>
            </div>
          ) : null}
        </div>
      </AppPageShell>
    </div>
  );
}
