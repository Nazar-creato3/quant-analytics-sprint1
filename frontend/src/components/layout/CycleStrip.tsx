"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { clsx } from "clsx";
import { IA_CYCLE, type CycleId } from "@/lib/iaCycle";

const PRIMARY: CycleId[] = ["learn", "evaluate", "risk", "act", "control"];

function cycleForPath(pathname: string): CycleId | "service" {
  for (const group of IA_CYCLE) {
    for (const item of group.items) {
      const href = item.href.split("#")[0];
      if (href === "/" && pathname === "/") return group.id;
      if (href !== "/" && (pathname === href || pathname.startsWith(`${href}/`))) {
        return group.id;
      }
    }
  }
  return "service";
}

export function CycleStrip() {
  const pathname = usePathname();
  const current = cycleForPath(pathname);
  return (
    <nav
      className="hidden md:flex items-center gap-1 overflow-x-auto scrollbar-none px-1"
      aria-label="Цикл пользователя"
      data-testid="ia-cycle-strip"
    >
      {IA_CYCLE.filter((g) => PRIMARY.includes(g.id as CycleId)).map((group, index) => {
        const first = group.items[0];
        const active = current === group.id;
        return (
          <span key={group.id} className="inline-flex items-center gap-1 shrink-0">
            {index > 0 ? <span className="text-qa-muted text-[10px]" aria-hidden>→</span> : null}
            <Link
              href={first.href}
              data-cycle={group.id}
              className={clsx(
                "px-1.5 py-0.5 rounded text-[10px] uppercase tracking-wide min-h-[28px] inline-flex items-center",
                "focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-terminal-accent/70",
                active
                  ? "text-terminal-accent bg-[var(--qa-active)] border border-terminal-accent/40"
                  : "text-qa-muted hover:text-qa-text",
              )}
            >
              {group.label}
            </Link>
          </span>
        );
      })}
    </nav>
  );
}
