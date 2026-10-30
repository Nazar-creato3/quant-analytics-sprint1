"use client";

import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { clsx } from "clsx";
import { Loader2, Search } from "lucide-react";
import { marketApi } from "@/lib/api";

interface DirectDealsSymbolPickerProps {
  symbol: string;
  onSelect: (symbol: string) => void;
}

export function DirectDealsSymbolPicker({ symbol, onSelect }: DirectDealsSymbolPickerProps) {
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);

  const q = query.trim();
  const { data, isFetching, isError } = useQuery({
    queryKey: ["universe-search", "direct-deals", q],
    queryFn: () => marketApi.searchUniverse({ q, limit: 40, category: "all", region: "all" }),
    enabled: open,
    staleTime: 15_000,
  });

  const options = useMemo(() => data?.items ?? [], [data]);

  return (
    <div className="relative min-w-[220px]">
      <div className="flex items-center gap-2 rounded-lg border border-qa-border bg-qa-panel-secondary px-2 py-1.5">
        <Search size={14} className="text-qa-muted shrink-0" />
        <input
          type="text"
          value={open ? query : symbol}
          onChange={(e) => {
            setQuery(e.target.value);
            setOpen(true);
          }}
          onFocus={() => {
            setQuery("");
            setOpen(true);
          }}
          onBlur={() => setTimeout(() => setOpen(false), 180)}
          placeholder="Тикер или название компании…"
          className="flex-1 bg-transparent text-sm font-mono text-white outline-none min-w-0"
          aria-label="Поиск по всем рынкам"
        />
        {isFetching && <Loader2 size={13} className="animate-spin text-qa-muted shrink-0" />}
      </div>
      {open && (
        <div className="absolute z-30 left-0 right-0 mt-1 max-h-80 overflow-y-auto rounded-lg border border-qa-border bg-qa-panel shadow-xl">
          {isError && (
            <div className="px-3 py-2 text-[10px] text-qa-warning border-b border-qa-border">
              Поиск вселенной недоступен
            </div>
          )}
          {options.map((item) => (
            <button
              key={`${item.source}:${item.symbol}`}
              type="button"
              onMouseDown={(e) => e.preventDefault()}
              onClick={() => {
                onSelect(item.symbol);
                setQuery("");
                setOpen(false);
              }}
              className={clsx(
                "w-full text-left px-3 py-2 text-xs hover:bg-[var(--qa-hover)]",
                item.symbol.toUpperCase() === symbol.toUpperCase()
                  ? "text-terminal-accent bg-[var(--qa-active)]"
                  : "text-qa-text",
              )}
            >
              <div className="flex items-center justify-between gap-2">
                <span className="font-mono">{item.symbol}</span>
                <span className="text-[10px] uppercase text-qa-muted">{item.exchange}</span>
              </div>
              <div className="mt-0.5 text-[10px] text-qa-muted truncate">
                {item.name} · {item.category_label_ru}
              </div>
            </button>
          ))}
          {!isFetching && options.length === 0 && (
            <div className="px-3 py-3 text-xs text-qa-muted">Нет совпадений по тикеру или названию</div>
          )}
        </div>
      )}
    </div>
  );
}
