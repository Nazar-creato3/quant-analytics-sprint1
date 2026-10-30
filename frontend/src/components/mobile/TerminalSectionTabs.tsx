"use client";

import {
  Activity,
  Bot,
  Calculator,
  Landmark,
  LineChart,
} from "lucide-react";
import { clsx } from "clsx";
import type { TerminalSection } from "@/types/terminal";

const ITEMS: Array<{
  id: TerminalSection;
  label: string;
  icon: typeof LineChart;
}> = [
  { id: "market", label: "Market", icon: LineChart },
  { id: "economic", label: "Econ", icon: Landmark },
  { id: "quant", label: "Quant", icon: Calculator },
  { id: "agents", label: "Agents", icon: Bot },
];

export function TerminalSectionTabs({
  section,
  onSection,
}: {
  section: TerminalSection;
  onSection: (s: TerminalSection) => void;
}) {
  return (
    <div className="lg:hidden shrink-0 border-b border-terminal-border bg-terminal-surface">
      <div className="flex items-center gap-1 px-2 py-1.5 overflow-x-auto">
        <Activity size={12} className="text-terminal-accent shrink-0" aria-hidden />
        {ITEMS.map((item) => {
          const Icon = item.icon;
          const active = section === item.id;
          return (
            <button
              key={item.id}
              type="button"
              className={clsx(
                "shrink-0 inline-flex items-center gap-1.5 px-3 py-2 min-h-[44px] rounded-lg text-[11px] font-semibold uppercase tracking-wide transition-colors",
                active
                  ? "bg-terminal-accent/15 text-terminal-accent border border-terminal-accent/40"
                  : "text-terminal-muted border border-transparent",
              )}
              onClick={() => onSection(item.id)}
              aria-current={active ? "page" : undefined}
            >
              <Icon size={13} aria-hidden />
              {item.label}
            </button>
          );
        })}
      </div>
    </div>
  );
}
