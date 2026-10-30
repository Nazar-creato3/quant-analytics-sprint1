"use client";

import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { clsx } from "clsx";
import { Pin, PinOff } from "lucide-react";
import { marketApi, watchlistApi, type UniverseSearchHit } from "@/lib/api";
import { WATCHLIST_QUERY_KEY } from "@/hooks/useEffectiveWatchlist";
import { DirectDealsWatchlistSparkline } from "@/components/direct-deals/DirectDealsWatchlistSparkline";

export type SearchCategoryId =
  | "all"
  | "equities"
  | "etf"
  | "crypto"
  | "fx"
  | "us"
  | "europe"
  | "asia"
  | "moex";

export const SEARCH_CATEGORIES: {
  id: SearchCategoryId;
  label: string;
  category: string;
  region: string;
}[] = [
  { id: "all", label: "Все", category: "all", region: "all" },
  { id: "moex", label: "Россия", category: "all", region: "moex" },
  { id: "equities", label: "Акции", category: "equities", region: "all" },
  { id: "etf", label: "ETF", category: "etf", region: "all" },
  { id: "crypto", label: "Крипто", category: "crypto", region: "all" },
  { id: "fx", label: "Валюты", category: "fx", region: "all" },
  { id: "us", label: "США", category: "all", region: "us" },
  { id: "europe", label: "Европа", category: "all", region: "europe" },
  { id: "asia", label: "Азия", category: "all", region: "asia" },
];

export function UniverseSearchField({
  inputRef,
  onPick,
  placeholder = "Тикер или название компании…",
  compact = false,
  filterId: controlledFilterId,
  onFilterChange,
  showPin = true,
  showSparklines = false,
  chrome = "default",
}: {
  inputRef?: React.RefObject<HTMLInputElement | null>;
  onPick?: (symbol: string) => void;
  placeholder?: string;
  compact?: boolean;
  filterId?: SearchCategoryId;
  onFilterChange?: (filterId: SearchCategoryId) => void;
  showPin?: boolean;
  showSparklines?: boolean;
  /** default: open catalog. compact: one-line field + dropdown. */
  chrome?: "default" | "thin" | "compact";
}) {
  const queryClient = useQueryClient();
  const rootRef = useRef<HTMLDivElement>(null);
  const [raw, setRaw] = useState("");
  const [debounced, setDebounced] = useState("");
  const [open, setOpen] = useState(false);
  const [internalFilterId, setInternalFilterId] = useState<SearchCategoryId>("all");
  const filterId = controlledFilterId ?? internalFilterId;
  const setFilterId = (next: SearchCategoryId) => {
    if (controlledFilterId == null) setInternalFilterId(next);
    onFilterChange?.(next);
  };
  const isCompact = chrome === "compact";
  const panelOpen = !isCompact || open;

  useEffect(() => {
    const handle = window.setTimeout(() => setDebounced(raw.trim()), 350);
    return () => window.clearTimeout(handle);
  }, [raw]);

  useEffect(() => {
    if (!isCompact || !open) return;
    const onDoc = (event: MouseEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [isCompact, open]);

  const filter = SEARCH_CATEGORIES.find((f) => f.id === filterId) ?? SEARCH_CATEGORIES[0];

  const search = useQuery({
    queryKey: ["universe-search", debounced, filter.category, filter.region, chrome],
    queryFn: () =>
      marketApi.searchUniverse({
        q: debounced,
        limit: isCompact ? 10 : 40,
        category: filter.category,
        region: filter.region,
      }),
    staleTime: 15_000,
    enabled: panelOpen,
  });

  const pinMut = useMutation({
    mutationFn: (hit: UniverseSearchHit) =>
      hit.pinned ? watchlistApi.unpin(hit.symbol) : watchlistApi.pin(hit.symbol),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: WATCHLIST_QUERY_KEY });
      queryClient.invalidateQueries({ queryKey: ["universe-search"] });
      queryClient.invalidateQueries({ queryKey: ["settings"] });
    },
  });

  const items = search.data?.items ?? [];
  const pick = (symbol: string) => {
    onPick?.(symbol);
    if (isCompact) {
      setRaw("");
      setOpen(false);
    }
  };

  return (
    <div
      ref={rootRef}
      className={clsx("space-y-1", isCompact && "relative w-full max-w-[17rem]")}
    >
      <input
        ref={inputRef}
        className={
          compact || isCompact
            ? "term-input !py-0.5 !text-[10px] w-full"
            : "w-full bg-cockpit-bg border border-cockpit-border rounded pl-2 pr-2 py-1 text-[10px] text-qa-text placeholder:text-qa-muted focus:outline-none focus:border-cockpit-border"
        }
        placeholder={placeholder || "Тикер или название компании…"}
        aria-label="Universal instrument search"
        value={raw}
        onChange={(e) => {
          setRaw(e.target.value);
          if (isCompact) setOpen(true);
        }}
        onFocus={() => {
          if (isCompact) setOpen(true);
        }}
      />
      {panelOpen && (
        <div
          className={clsx(
            isCompact &&
              "absolute left-0 right-0 top-full z-30 mt-0.5 rounded bg-cockpit-panel border border-cockpit-border shadow-lg p-1",
          )}
        >
          <div className="flex flex-wrap gap-0.5">
            {SEARCH_CATEGORIES.map((f) => (
              <button
                key={f.id}
                type="button"
                onClick={() => setFilterId(f.id)}
                className={clsx(
                  "px-1 py-0.5 rounded text-[8px] uppercase",
                  filterId === f.id
                    ? "bg-terminal-accent-muted text-terminal-text"
                    : "text-terminal-muted hover:text-terminal-text",
                )}
              >
                {f.label}
              </button>
            ))}
          </div>
          <div
            className={clsx(
              "overflow-y-auto",
              isCompact
                ? "max-h-36"
                : chrome === "thin"
                  ? "max-h-[28rem]"
                  : "max-h-[28rem] border-t border-terminal-border/60",
            )}
          >
            {search.isFetching && items.length === 0 && (
              <p className="px-1 py-1 text-[9px] text-terminal-muted">Поиск…</p>
            )}
            {items.map((hit, index) => (
              <div
                key={`${hit.source}:${hit.symbol}`}
                className="flex items-center gap-1 px-1 py-0.5 hover:bg-terminal-accent-muted/40"
              >
                <button
                  type="button"
                  className="flex-1 min-w-0 text-left"
                  onClick={() => pick(hit.symbol)}
                >
                  <span className="block font-mono text-[10px] text-terminal-text truncate">
                    {hit.symbol}
                    {!isCompact && hit.data_tier === "data_only" ? (
                      <span className="ml-1 text-[8px] uppercase text-terminal-muted font-sans">
                        {hit.data_tier_label_ru || "котировки"}
                      </span>
                    ) : null}
                  </span>
                  {!isCompact ? (
                    <span className="block text-[8px] text-terminal-muted truncate">
                      {hit.name} · {hit.exchange}
                    </span>
                  ) : (
                    <span className="block text-[8px] text-terminal-muted truncate">{hit.name}</span>
                  )}
                </button>
                {showSparklines ? (
                  <DirectDealsWatchlistSparkline
                    ticker={hit.symbol}
                    index={index}
                    priority={index < 8}
                    width={56}
                    height={18}
                  />
                ) : null}
                {showPin ? (
                  <button
                    type="button"
                    title={hit.pinned ? "Убрать из избранного" : "Закрепить в Watchlist"}
                    className="p-0.5 text-terminal-muted hover:text-terminal-accent"
                    onClick={() => pinMut.mutate(hit)}
                  >
                    {hit.pinned ? <PinOff size={11} /> : <Pin size={11} />}
                  </button>
                ) : null}
              </div>
            ))}
            {!search.isFetching && items.length === 0 && (
              <p className="px-1 py-1 text-[9px] text-terminal-muted">Нет совпадений во вселенной</p>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
