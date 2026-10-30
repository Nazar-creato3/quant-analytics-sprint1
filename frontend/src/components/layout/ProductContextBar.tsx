"use client";

import { useProductContext } from "@/contexts/ProductContext";

export function ProductContextBar() {
  const { activeTicker, activeAccount, setActiveAccount, period, setPeriod, currency, setCurrency } =
    useProductContext();
  return (
    <div
      className="hidden lg:flex items-center gap-1 text-[10px] text-qa-muted"
      data-testid="product-context-bar"
    >
      <span className="font-mono text-qa-text">{activeTicker || "—"}</span>
      <label className="sr-only" htmlFor="qa-account">
        Счёт
      </label>
      <input
        id="qa-account"
        value={activeAccount}
        onChange={(e) => setActiveAccount(e.target.value)}
        className="w-16 bg-transparent border border-cockpit-border rounded px-1 py-0.5 min-h-[28px]"
      />
      <label className="sr-only" htmlFor="qa-period">
        Период
      </label>
      <select
        id="qa-period"
        value={period}
        onChange={(e) => setPeriod(e.target.value as typeof period)}
        className="bg-transparent border border-cockpit-border rounded px-1 py-0.5 min-h-[28px]"
      >
        <option value="1d">1д</option>
        <option value="1w">1н</option>
        <option value="1m">1м</option>
        <option value="ytd">YTD</option>
        <option value="inception">с начала</option>
      </select>
      <label className="sr-only" htmlFor="qa-ccy">
        Валюта
      </label>
      <select
        id="qa-ccy"
        value={currency}
        onChange={(e) => setCurrency(e.target.value as typeof currency)}
        className="bg-transparent border border-cockpit-border rounded px-1 py-0.5 min-h-[28px]"
      >
        <option value="RUB">RUB</option>
        <option value="USD">USD</option>
      </select>
    </div>
  );
}
