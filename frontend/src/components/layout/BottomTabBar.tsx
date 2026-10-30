"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { clsx } from "clsx";
import {
  LayoutDashboard,
  MessageCircle,
  BarChart3,
  Terminal,
  MoreHorizontal,
  ArrowLeftRight,
  Grid,
  Shield,
  Workflow,
  Filter,
  Globe,
  Settings,
  UserCircle,
} from "lucide-react";
import { useEffect, useState } from "react";

const PRIMARY_TABS = [
  { id: "terminal", label: "Узнать", href: "/terminal", icon: Terminal },
  { id: "forecasting", label: "Оценить", href: "/forecasting", icon: BarChart3 },
  { id: "portfolio", label: "Портфель", href: "/portfolio", icon: Shield },
  { id: "direct-deals", label: "Сделки", href: "/direct-deals", icon: ArrowLeftRight },
  { id: "dashboard", label: "Контроль", href: "/", icon: LayoutDashboard },
];

const MORE_TABS = [
  { id: "chat", label: "Чат", href: "/chat", icon: MessageCircle },
  { id: "bots", label: "Боты", href: "/bots", icon: Grid },
  { id: "composer", label: "Стратегии", href: "/strategy-composer", icon: Workflow },
  { id: "markets", label: "Рынки", href: "/markets", icon: Globe },
  { id: "screener", label: "Скринер", href: "/screener", icon: Filter },
  { id: "account", label: "Кабинет", href: "/account", icon: UserCircle },
  { id: "settings", label: "Настройки", href: "/settings", icon: Settings },
];

function isActive(pathname: string, href: string): boolean {
  if (href === "/") return pathname === "/";
  return pathname === href || pathname.startsWith(`${href}/`);
}

export function BottomTabBar() {
  const pathname = usePathname();
  const [moreOpen, setMoreOpen] = useState(false);
  const moreActive = MORE_TABS.some((t) => isActive(pathname, t.href));

  useEffect(() => {
    setMoreOpen(false);
  }, [pathname]);

  useEffect(() => {
    if (!moreOpen) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setMoreOpen(false);
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [moreOpen]);

  if (pathname.startsWith("/login") || pathname.startsWith("/signup") || pathname.startsWith("/apply")) {
    return null;
  }

  return (
    <>
      {moreOpen && (
        <div
          className="md:hidden fixed inset-0 z-40 bg-black/50"
          onClick={() => setMoreOpen(false)}
          aria-hidden
        />
      )}
      {moreOpen && (
        <div
          role="menu"
          className="md:hidden fixed inset-x-0 bottom-14 z-50 border-t border-cockpit-border bg-cockpit-panel px-2 py-2 shadow-[0_-8px_24px_rgba(0,0,0,0.35)]"
        >
          <div className="flex items-center gap-1 overflow-x-auto scrollbar-none">
            {MORE_TABS.map((tab) => {
              const Icon = tab.icon;
              return (
                <Link
                  key={tab.id}
                  href={tab.href}
                  onClick={() => setMoreOpen(false)}
                  className={clsx(
                    "flex shrink-0 items-center gap-1.5 min-h-[44px] rounded-lg px-3 text-xs font-medium whitespace-nowrap",
                    isActive(pathname, tab.href)
                      ? "text-terminal-accent bg-terminal-accent/10"
                      : "text-qa-muted hover:text-qa-text hover:bg-[var(--qa-hover)]",
                  )}
                >
                  {Icon ? <Icon size={16} className="shrink-0" aria-hidden /> : null}
                  <span>{tab.label}</span>
                </Link>
              );
            })}
          </div>
        </div>
      )}
      <nav
        className="md:hidden fixed bottom-0 inset-x-0 z-50 border-t border-cockpit-border bg-cockpit-panel/95 backdrop-blur-md safe-area-pb"
        aria-label="Primary navigation"
      >
        <div className="flex items-stretch justify-around h-14">
          {PRIMARY_TABS.map((tab) => {
            const Icon = tab.icon;
            const active = isActive(pathname, tab.href);
            return (
              <Link
                key={tab.id}
                href={tab.href}
                className={clsx(
                  "flex flex-1 flex-col items-center justify-center gap-0.5 min-w-[44px] min-h-[44px]",
                  active ? "text-terminal-accent" : "text-qa-muted",
                )}
              >
                <Icon size={20} strokeWidth={active ? 2.25 : 1.75} />
                <span className="text-[10px] font-medium">{tab.label}</span>
              </Link>
            );
          })}
          <button
            type="button"
            onClick={() => setMoreOpen((v) => !v)}
            className={clsx(
              "flex flex-1 flex-col items-center justify-center gap-0.5 min-w-[44px] min-h-[44px]",
              moreActive || moreOpen ? "text-terminal-accent" : "text-qa-muted",
            )}
            aria-expanded={moreOpen}
            aria-label="Другие разделы"
          >
            <MoreHorizontal size={20} />
            <span className="text-[10px] font-medium">Ещё</span>
          </button>
        </div>
      </nav>
    </>
  );
}
