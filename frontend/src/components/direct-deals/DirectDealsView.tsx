"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useRouter, useSearchParams } from "next/navigation";
import { clsx } from "clsx";
import { AlertTriangle } from "lucide-react";
import { LightweightChartLoader } from "@/components/charts/LightweightChartLoader";
import { OrderTicket, type OrderSide } from "@/components/orders/OrderTicket";
import { ManualOrdersPanel } from "@/components/orders/ManualOrdersPanel";
import { DirectDealsOrderBookPanel } from "@/components/direct-deals/DirectDealsOrderBookPanel";
import { DirectDealsQuoteHeader, type QuoteView } from "@/components/direct-deals/DirectDealsQuoteHeader";
import { DirectDealsSymbolPicker } from "@/components/direct-deals/DirectDealsSymbolPicker";
import { DirectDealsWatchlistSidebar } from "@/components/direct-deals/DirectDealsWatchlistSidebar";
import { DirectDealsInstrumentTabs } from "@/components/direct-deals/DirectDealsInstrumentTabs";
import { DirectDealsTradesTab } from "@/components/direct-deals/DirectDealsTradesTab";
import { DirectDealsInfoTab } from "@/components/direct-deals/DirectDealsInfoTab";
import { DirectDealsDividendsTab } from "@/components/direct-deals/DirectDealsDividendsTab";
import { DirectDealsRegulatoryTab } from "@/components/direct-deals/DirectDealsRegulatoryTab";
import type { DirectDealsTabId } from "@/components/direct-deals/direct-deals-tabs";
import { ErrorBoundary } from "@/components/ui/ErrorBoundary";
import { marketApi, ordersApi, portfolioApi } from "@/lib/api";
import { DIRECT_DEALS_POLL, parseDirectDealsSearch } from "@/lib/direct-deals";
import { useActiveTicker } from "@/contexts/ActiveTickerContext";
import type { OrderTicketPrefill } from "@/types";

function extractQuote(raw: Record<string, unknown>): QuoteView {
  const num = (v: unknown): number | null => {
    const n = typeof v === "number" ? v : parseFloat(String(v ?? ""));
    return Number.isFinite(n) ? n : null;
  };
  const technical = (raw.technical ?? raw.technicals ?? {}) as Record<string, unknown>;
  const price = num(raw.price ?? raw.last);
  const bid = num(raw.bid);
  const ask = num(raw.ask);
  const changePct = num(raw.change_pct ?? raw.changePercent ?? raw.percent_change);
  const volume = num(raw.volume ?? raw.volume_24h);
  const high = num(raw.high ?? raw.day_high ?? raw.high_24h);
  const low = num(raw.low ?? raw.day_low ?? raw.low_24h);
  const week52High = num(technical.week52_high ?? technical.week52High ?? raw.week52_high);
  const week52Low = num(technical.week52_low ?? technical.week52Low ?? raw.week52_low);
  const asOf = typeof raw.as_of === "string" ? raw.as_of : typeof raw.timestamp === "string" ? raw.timestamp : null;
  const stale = Boolean(raw.stale ?? raw.degraded);
  const error = typeof raw.error === "string" ? raw.error : null;
  const session = typeof raw.session === "string" ? raw.session : typeof raw.session_status === "string" ? raw.session_status : null;
  const market = typeof raw.exchange === "string" ? raw.exchange : typeof raw.market === "string" ? raw.market : null;
  return { price, bid, ask, changePct, volume, high, low, week52High, week52Low, asOf, stale, error, session, market };
}

const DIRECT_DEALS_SYMBOL_STORAGE_KEY = "direct-deals:selected-symbol";
const DIRECT_DEALS_TAB_STORAGE_KEY = "direct-deals:active-tab";

export function DirectDealsView() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const urlParams = useMemo(
    () => parseDirectDealsSearch(searchParams.toString()),
    [searchParams],
  );

  const { setActiveTicker } = useActiveTicker();
  const [symbol, setSymbol] = useState(urlParams.symbol || "BTCUSDT");
  const [side, setSide] = useState<OrderSide>(urlParams.side ?? "buy");
  const [limitPriceHint, setLimitPriceHint] = useState<number | undefined>();
  const [ticketKey, setTicketKey] = useState(0);
  const [activeTab, setActiveTab] = useState<DirectDealsTabId>("book");

  const maneuverId = urlParams.maneuverId;

  useEffect(() => {
    if (urlParams.symbol) setSymbol(urlParams.symbol);
    if (urlParams.side) setSide(urlParams.side);
  }, [urlParams.symbol, urlParams.side]);

  useEffect(() => {
    if (urlParams.symbol || typeof window === "undefined") return;
    const stored = window.localStorage.getItem(DIRECT_DEALS_SYMBOL_STORAGE_KEY);
    if (stored?.trim()) setSymbol(stored.trim().toUpperCase());
    const storedTab = window.localStorage.getItem(DIRECT_DEALS_TAB_STORAGE_KEY) as DirectDealsTabId | null;
    if (storedTab === "book" || storedTab === "trade" || storedTab === "tape" || storedTab === "info" || storedTab === "dividends" || storedTab === "regulatory") {
      setActiveTab(storedTab);
    }
  }, [urlParams.symbol]);

  useEffect(() => {
    if (typeof window === "undefined" || !symbol) return;
    window.localStorage.setItem(DIRECT_DEALS_SYMBOL_STORAGE_KEY, symbol.toUpperCase());
  }, [symbol]);

  const handleTabChange = (tab: DirectDealsTabId) => {
    setActiveTab(tab);
    if (typeof window !== "undefined") {
      window.localStorage.setItem(DIRECT_DEALS_TAB_STORAGE_KEY, tab);
    }
  };

  const syncUrl = useCallback(
    (nextSymbol: string, nextManeuver?: string) => {
      const q = new URLSearchParams();
      q.set("symbol", nextSymbol);
      q.set("side", side);
      if (nextManeuver) q.set("maneuver", nextManeuver);
      router.replace(`/direct-deals?${q.toString()}`, { scroll: false });
    },
    [router, side],
  );

  const handleSymbolChange = (next: string) => {
    const normalized = next.toUpperCase();
    setSymbol(normalized);
    setLimitPriceHint(undefined);
    syncUrl(normalized, maneuverId);
    setTicketKey((k) => k + 1);
    setActiveTicker(normalized);
  };

  const { data: quoteRaw, isLoading: quoteLoading, isError: quoteError } = useQuery({
    queryKey: ["direct-deals-quote", symbol],
    // Fast path (no enrich): Alpaca/MOEX/Binance price+change within FE timeout.
    // Avoid forceRefresh on poll — it stampedes providers and starved watchlist quotes.
    queryFn: () => marketApi.getQuote(symbol),
    enabled: Boolean(symbol),
    refetchInterval: DIRECT_DEALS_POLL.quoteMs,
    staleTime: 1000,
    retry: 1,
  });

  const quote = useMemo(
    () =>
      extractQuote({
        ...(quoteRaw ?? {}),
        error: quoteError ? "Котировка недоступна" : undefined,
      }),
    [quoteRaw, quoteError],
  );

  const { data: prefill, isLoading: prefillLoading } = useQuery({
    queryKey: ["order-prefill", maneuverId],
    queryFn: () => ordersApi.prefillFromManeuver(maneuverId!),
    enabled: Boolean(maneuverId),
  });

  useEffect(() => {
    if (!prefill) return;
    if (prefill.ticker) setSymbol(prefill.ticker.toUpperCase());
    if (prefill.side) setSide(prefill.side);
    if (prefill.limit_price) setLimitPriceHint(prefill.limit_price);
  }, [prefill]);

  const { data: balances } = useQuery({
    queryKey: ["portfolio-balances"],
    queryFn: () => portfolioApi.balances(),
    refetchInterval: DIRECT_DEALS_POLL.balancesMs,
    staleTime: 5000,
  });

  const availableBalanceUsd = useMemo(() => {
    const total =
      balances?.total_trading_usd ??
      balances?.total_usd ??
      balances?.total_balance_usd;
    return typeof total === "number" && total > 0 ? total : 100_000;
  }, [balances]);

  const ticketPrefill: OrderTicketPrefill | null = prefill ?? null;

  return (
    <div className="flex flex-1 bg-qa-bg">
      <DirectDealsWatchlistSidebar
        selectedSymbol={symbol}
        onSelectSymbol={handleSymbolChange}
      />

      <div className="flex flex-col flex-1 min-w-0">
        <div className="px-3 py-2 border-b border-qa-border bg-qa-panel/80 flex flex-wrap items-center gap-3 shrink-0 sticky top-0 z-10">
          <DirectDealsSymbolPicker symbol={symbol} onSelect={handleSymbolChange} />
          {maneuverId && (
            <div className="text-[11px] text-terminal-accent border border-terminal-accent/30 rounded px-2 py-1">
              Заполнено из манёвра · отправка только вручную
            </div>
          )}
          <div className="ml-auto text-[10px] text-qa-muted tabular-nums">
            Доступно ≈ $
            {availableBalanceUsd.toLocaleString(undefined, { maximumFractionDigits: 0 })}
            {balances?.as_of ? ` · ${new Date(balances.as_of).toLocaleTimeString()}` : ""}
          </div>
        </div>

        <div className="p-3 pb-8 flex flex-col gap-3">
          <DirectDealsQuoteHeader symbol={symbol} quote={quote} loading={quoteLoading} />

          <div className="rounded-lg border border-qa-border bg-qa-panel p-2 min-h-[200px]">
            <ErrorBoundary>
              <LightweightChartLoader
                ticker={symbol}
                timeframe="1h"
                height={240}
                showVolume
                allowMockFallback={false}
              />
            </ErrorBoundary>
          </div>

          <DirectDealsInstrumentTabs
            activeTab={activeTab}
            onTabChange={handleTabChange}
            symbol={symbol}
          />

          <div className="rounded-lg border border-qa-border bg-qa-panel flex flex-col min-h-[320px]">
            {activeTab === "book" && (
              <div className="min-h-[320px] p-2">
                <DirectDealsOrderBookPanel
                  ticker={symbol}
                  limitPrice={limitPriceHint}
                  side={side}
                  onSelectPrice={(p) => setLimitPriceHint(p)}
                />
              </div>
            )}

            {activeTab === "trade" && (
              <div className="p-3 flex flex-col gap-3">
                {prefillLoading && maneuverId ? (
                  <div className="rounded-lg border border-qa-border bg-qa-panel-secondary p-4 text-sm text-qa-muted shrink-0">
                    Загружаем данные манёвра…
                  </div>
                ) : (
                  <div className="shrink-0">
                    <OrderTicket
                      key={`${symbol}-${ticketKey}-${maneuverId ?? "none"}`}
                      ticker={symbol}
                      prefill={ticketPrefill}
                      availableBalanceUsd={availableBalanceUsd}
                      externalLimitPrice={limitPriceHint}
                      onSideChange={setSide}
                      showOrderBook={false}
                      bookPollMs={DIRECT_DEALS_POLL.orderBookMs}
                      quoteBid={quote.bid}
                      quoteAsk={quote.ask}
                      onSubmitted={() => {
                        setLimitPriceHint(undefined);
                      }}
                    />
                  </div>
                )}

                {maneuverId && (
                  <div className="flex items-start gap-2 text-[11px] text-qa-muted rounded border border-qa-border bg-qa-panel-secondary/50 px-3 py-2 shrink-0">
                    <AlertTriangle size={12} className="text-terminal-accent shrink-0 mt-0.5" />
                    Проверьте размер и стопы перед отправкой. Одобрение манёвра само по себе заявку не выставляет.
                  </div>
                )}

                <ManualOrdersPanel
                  ticker={symbol}
                  pollMs={DIRECT_DEALS_POLL.ordersMs}
                  className="min-h-[200px]"
                />
              </div>
            )}

            {activeTab === "tape" && <DirectDealsTradesTab ticker={symbol} />}

            {activeTab === "info" && <DirectDealsInfoTab ticker={symbol} />}

            {activeTab === "dividends" && <DirectDealsDividendsTab ticker={symbol} />}

            {activeTab === "regulatory" && <DirectDealsRegulatoryTab ticker={symbol} />}
          </div>
        </div>
      </div>
    </div>
  );
}
