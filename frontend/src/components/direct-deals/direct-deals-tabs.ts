"use client";

import { classifySymbol } from "@/lib/asset-class";

export type DirectDealsTabId = "book" | "trade" | "tape" | "info" | "dividends" | "regulatory";

export const DIRECT_DEALS_TABS: { id: DirectDealsTabId; label: string; equitiesOnly?: boolean; usEquitiesOnly?: boolean }[] = [
  { id: "book", label: "Стакан" },
  { id: "trade", label: "Торговля" },
  { id: "tape", label: "Торги" },
  { id: "info", label: "Инфо" },
  { id: "dividends", label: "Дивиденды", equitiesOnly: true },
  { id: "regulatory", label: "SEC / FINRA", usEquitiesOnly: true },
];

/** Heuristic: show dividends tab for non-crypto equity symbols (not FX). */
export function isEquitySymbol(symbol: string): boolean {
  const routed = classifySymbol(symbol);
  return routed.routingClass === "us_equity_index" || routed.routingClass === "international"
    ? routed.market !== "index" && routed.showVolume
    : false;
}

/** US-listed equities only — SEC/FINRA regulatory data. */
export function isUsEquitySymbol(symbol: string): boolean {
  const routed = classifySymbol(symbol);
  return routed.routingClass === "us_equity_index" && routed.market === "us" && routed.showVolume;
}
