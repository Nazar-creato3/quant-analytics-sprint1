"use client";

import type { RefObject } from "react";
import { UniverseSearchField } from "@/components/search/UniverseSearchField";
import type { TerminalWatchItem } from "@/types/terminal";

export function WatchlistDensePanel({
  focusSymbol,
  onFocus,
  filterRef,
}: {
  rows?: TerminalWatchItem[];
  focusSymbol?: string | null;
  onFocus?: (symbol: string) => void;
  filterRef?: RefObject<HTMLInputElement | null>;
}) {
  return (
    <div className="px-1.5 py-1">
      <UniverseSearchField
        inputRef={filterRef}
        onPick={onFocus}
        compact
        placeholder="Поиск по всем рынкам"
        showPin={false}
        showSparklines
        chrome="thin"
      />
      {focusSymbol ? (
        <p className="px-0.5 pt-1 text-[8px] uppercase text-terminal-muted">Сейчас: {focusSymbol}</p>
      ) : null}
    </div>
  );
}
