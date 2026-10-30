"use client";

import { useQuery } from "@tanstack/react-query";
import { clsx } from "clsx";
import { Loader2 } from "lucide-react";
import { ordersApi } from "@/lib/api";
import { DIRECT_DEALS_POLL } from "@/lib/direct-deals";
import { useVisiblePollInterval } from "@/hooks/useDocumentVisibility";
import { OrderBookDepth } from "@/components/orders/OrderBookDepth";

interface DirectDealsOrderBookPanelProps {
  ticker: string;
  limitPrice?: number;
  side: "buy" | "sell";
  onSelectPrice?: (price: number) => void;
}

function formatMsk(iso: string | null | undefined): string {
  if (!iso) return "—";
  try {
    return new Intl.DateTimeFormat("ru-RU", {
      timeZone: "Europe/Moscow",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    }).format(new Date(iso));
  } catch {
    return "—";
  }
}

function hasBookData(book: {
  bids: unknown[];
  asks: unknown[];
  mid_price?: number | null;
} | undefined): boolean {
  if (!book) return false;
  if (book.mid_price != null && Number.isFinite(book.mid_price)) return true;
  return book.bids.length > 0 || book.asks.length > 0;
}

export function DirectDealsOrderBookPanel({
  ticker,
  limitPrice,
  side,
  onSelectPrice,
}: DirectDealsOrderBookPanelProps) {
  const pollMs = useVisiblePollInterval(DIRECT_DEALS_POLL.orderBookMs);

  const { data: book, isLoading, isError, isFetched } = useQuery({
    queryKey: ["order-book", ticker],
    queryFn: () => ordersApi.orderBook(ticker),
    enabled: Boolean(ticker),
    refetchInterval: pollMs,
    staleTime: 250,
    placeholderData: (prev) => prev,
  });

  const empty = isFetched && !hasBookData(book);
  const showInitialLoad = isLoading && !book;

  return (
    <div className="rounded-lg border border-qa-border bg-qa-panel flex flex-col min-h-[280px]">
      <div className="px-3 py-2 border-b border-qa-border flex items-center justify-between shrink-0">
        <h2 className="text-xs font-semibold text-qa-text uppercase tracking-wide">Стакан</h2>
        <span className="text-[10px] text-qa-muted tabular-nums">
          {book?.source && !/^[a-z_]+$/.test(book.source) ? `${book.source} · ` : ""}
          {formatMsk(book?.as_of)} МСК
        </span>
      </div>
      {book?.session_label ? (
        <p className="px-3 py-1.5 text-[11px] text-terminal-accent border-b border-qa-border" data-testid="book-session-label" title={book.depth_unavailable_reason ?? undefined}>
          {book.session_label}
        </p>
      ) : null}
      <div className="flex-1 overflow-y-auto p-3 min-h-0">
        {showInitialLoad ? (
          <div className="text-xs text-qa-muted flex items-center gap-2 py-8 justify-center">
            <Loader2 size={14} className="animate-spin" /> Загрузка стакана…
          </div>
        ) : hasBookData(book) ? (
          <OrderBookDepth
            book={book!}
            limitPrice={limitPrice}
            side={side}
            depth={12}
            animated
            onSelectPrice={onSelectPrice}
          />
        ) : (
          <p
            className={clsx(
              "text-xs text-center py-8",
              isError || empty ? "text-warning" : "text-qa-muted",
            )}
          >
            {isError ? "Не удалось загрузить стакан" : "Стакан по этой бумаге сейчас недоступен"}
          </p>
        )}
      </div>
    </div>
  );
}
