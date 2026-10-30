"use client";

import { clsx } from "clsx";
import { DIRECT_DEALS_TABS, isEquitySymbol, isUsEquitySymbol, type DirectDealsTabId } from "./direct-deals-tabs";

interface DirectDealsInstrumentTabsProps {
  activeTab: DirectDealsTabId;
  onTabChange: (tab: DirectDealsTabId) => void;
  symbol: string;
}

export function DirectDealsInstrumentTabs({
  activeTab,
  onTabChange,
  symbol,
}: DirectDealsInstrumentTabsProps) {
  const showEquityTabs = isEquitySymbol(symbol);
  const showUsEquityTabs = isUsEquitySymbol(symbol);
  const tabs = DIRECT_DEALS_TABS.filter(
    (t) =>
      (!t.equitiesOnly || showEquityTabs) &&
      (!t.usEquitiesOnly || showUsEquityTabs),
  );

  return (
    <div className="flex flex-wrap gap-1 border-b border-qa-border pb-2 shrink-0">
      {tabs.map((tab) => (
        <button
          key={tab.id}
          type="button"
          onClick={() => onTabChange(tab.id)}
          className={clsx(
            "px-3 py-1.5 text-[11px] font-medium rounded-t transition-colors",
            activeTab === tab.id
              ? "bg-[var(--qa-active)] text-terminal-accent border border-terminal-accent/40 border-b-transparent -mb-[1px]"
              : "text-qa-muted hover:text-qa-text hover:bg-[var(--qa-hover)] border border-transparent",
          )}
        >
          {tab.label}
        </button>
      ))}
    </div>
  );
}
