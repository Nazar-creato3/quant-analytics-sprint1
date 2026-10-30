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
  hint: string;
  icon: typeof LineChart;
  keyHint: string;
}> = [
  { id: "market", label: "Рынок", hint: "Индексы, пульс, риск", icon: LineChart, keyHint: "1" },
  { id: "economic", label: "Экономика", hint: "Календарь и макро", icon: Landmark, keyHint: "2" },
  { id: "quant", label: "Факторы", hint: "Оценки и вклад", icon: Calculator, keyHint: "3" },
  { id: "agents", label: "Сценарии", hint: "Разбор по шагам", icon: Bot, keyHint: "4" },
];

export function TerminalSidebar({
  section,
  onSection,
}: {
  section: TerminalSection;
  onSection: (s: TerminalSection) => void;
}) {
  return (
    <aside className="hidden lg:flex flex-col w-[148px] shrink-0 border-r border-terminal-border bg-terminal-surface">
      <div className="px-2 py-2 border-b border-terminal-border">
        <div className="flex items-center gap-1.5 text-terminal-accent">
          <Activity size={12} aria-hidden />
          <span className="text-[10px] font-bold tracking-[0.14em] uppercase">Терминал</span>
        </div>
        <p className="text-[9px] text-terminal-muted mt-1 leading-snug">
          Рабочее место
        </p>
      </div>
      <nav className="flex-1 py-1" aria-label="Разделы терминала">
        {ITEMS.map((item) => {
          const Icon = item.icon;
          const active = section === item.id;
          return (
            <button
              key={item.id}
              type="button"
              className={clsx("term-nav-item", active && "active")}
              onClick={() => onSection(item.id)}
              aria-current={active ? "page" : undefined}
            >
              <Icon size={13} className="shrink-0" aria-hidden />
              <span className="flex-1 text-left">
                <span className="block font-semibold uppercase tracking-wide text-[10px]">
                  {item.label}
                </span>
                <span className="block text-[9px] opacity-70 normal-case tracking-normal font-normal">
                  {item.hint}
                </span>
              </span>
              <kbd className="text-[9px] text-terminal-muted border border-terminal-border px-1">
                {item.keyHint}
              </kbd>
            </button>
          );
        })}
      </nav>
      <div className="px-2 py-2 border-t border-terminal-border text-[9px] text-terminal-muted space-y-0.5">
        <p><span className="text-terminal-accent">?</span> — сочетания клавиш</p>
        <p>Для сотрудников</p>
      </div>
    </aside>
  );
}
