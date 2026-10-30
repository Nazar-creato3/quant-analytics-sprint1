"use client";

import { Suspense, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { usePathname, useSearchParams } from "next/navigation";
import { clsx } from "clsx";
import { ArrowLeftRight, Briefcase, Check, ChevronDown, Eye, Layers, type LucideIcon } from "lucide-react";
import { watchlistApi } from "@/lib/api";
import { useProductContext } from "@/contexts/ProductContext";

type Variant = "chips" | "menu";

const CHIP =
  "inline-flex items-center gap-1.5 rounded-full border border-cockpit-border bg-[var(--qa-hover)]/40 " +
  "px-2.5 py-1 text-[11px] leading-none text-qa-text/85 whitespace-nowrap transition-colors " +
  "hover:border-terminal-accent/60 hover:text-terminal-accent " +
  "focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-terminal-accent/70";

const ITEM =
  "flex w-full items-center gap-2 rounded-md px-2.5 py-2 text-xs text-qa-text/85 whitespace-nowrap text-left " +
  "hover:bg-[var(--qa-hover)] hover:text-terminal-accent";

/**
 * Next steps for the current ticker, shared by every section.
 * `chips` — a tidy row of buttons for page headers.
 * `menu` — one small «Действия» button for list rows (news, markets, screener),
 * so the same links are not repeated under every line.
 */
export function CrossActions({ ticker, variant = "chips" }: { ticker?: string; variant?: Variant }) {
  return (
    <Suspense
      fallback={
        <div
          data-testid="cross-actions"
          data-ticker={(ticker || "").toUpperCase() || undefined}
          className="flex flex-wrap gap-1.5"
        />
      }
    >
      <CrossActionsInner ticker={ticker} variant={variant} />
    </Suspense>
  );
}

type Action = {
  key: string;
  label: string;
  icon: LucideIcon;
  href?: string;
  onClick?: () => void;
  testId?: string;
};

function useActions(ticker: string | undefined, rowTicker: boolean): { symbol: string; actions: Action[] } {
  const { activeTicker } = useProductContext();
  const params = useSearchParams();
  const pathname = usePathname();
  const [pinned, setPinned] = useState(false);
  const fromUrl = (params.get("symbol") || params.get("ticker") || "").toUpperCase();
  // A list row always acts on its own ticker; a page header follows the URL first.
  const symbol = (rowTicker ? ticker || fromUrl || activeTicker : fromUrl || ticker || activeTicker || "")?.toUpperCase() ?? "";
  const q = symbol ? `?symbol=${encodeURIComponent(symbol)}` : "";
  const all: Action[] = [
    {
      key: "portfolio",
      label: "Влияние на портфель",
      icon: Briefcase,
      href: `/portfolio?tab=risk${symbol ? `&add=${encodeURIComponent(symbol)}` : ""}`,
      testId: "cross-portfolio",
    },
    { key: "deal", label: "Купить или продать", icon: ArrowLeftRight, href: `/direct-deals${q}`, testId: "cross-deal" },
    { key: "maneuvers", label: "Манёвры", icon: Layers, href: `/act${q}`, testId: "cross-maneuvers" },
  ];
  if (symbol) {
    all.push({
      key: "watch",
      label: pinned ? "В наблюдении" : "В наблюдение",
      icon: pinned ? Check : Eye,
      testId: "cross-watch",
      onClick: () => {
        if (pinned) return;
        void watchlistApi.pin(symbol).then(() => setPinned(true)).catch(() => undefined);
      },
    });
  }
  // Never offer a link to the page the user is already on.
  const actions = all.filter((a) => !a.href || a.href.split("?")[0] !== pathname);
  return { symbol, actions };
}

function ActionLink({ action, className }: { action: Action; className: string }) {
  const Icon = action.icon;
  const body = (
    <>
      <Icon size={12} className="shrink-0 opacity-80" aria-hidden />
      <span>{action.label}</span>
    </>
  );
  if (!action.href) {
    return (
      <button type="button" data-testid={action.testId} onClick={action.onClick} className={className}>
        {body}
      </button>
    );
  }
  return (
    <Link data-testid={action.testId} href={action.href} className={className}>
      {body}
    </Link>
  );
}

function CrossActionsInner({ ticker, variant }: { ticker?: string; variant: Variant }) {
  const { symbol, actions } = useActions(ticker, variant === "menu");

  if (variant === "menu") {
    return <ActionsMenu symbol={symbol} actions={actions} />;
  }
  return (
    <div className="flex flex-wrap items-center gap-1.5" data-testid="cross-actions" data-ticker={symbol || undefined}>
      {actions.map((a) => (
        <ActionLink key={a.key} action={a} className={CHIP} />
      ))}
    </div>
  );
}

function ActionsMenu({ symbol, actions }: { symbol: string; actions: Action[] }) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", onDoc);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDoc);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  return (
    <div ref={ref} className="relative inline-block" data-testid="cross-actions" data-ticker={symbol || undefined}>
      <button
        type="button"
        onClick={(e) => {
          e.stopPropagation();
          setOpen((v) => !v);
        }}
        aria-expanded={open}
        aria-haspopup="menu"
        className={clsx(CHIP, open && "border-terminal-accent/60 text-terminal-accent")}
      >
        <span>Действия{symbol ? ` · ${symbol}` : ""}</span>
        <ChevronDown size={12} aria-hidden className={clsx("transition-transform", open && "rotate-180")} />
      </button>
      {open ? (
        <div
          role="menu"
          className="absolute left-0 top-full z-50 mt-1 min-w-[210px] rounded-lg border border-cockpit-border bg-cockpit-surface p-1.5 shadow-xl"
        >
          {actions.map((a) => (
            <ActionLink key={a.key} action={a} className={ITEM} />
          ))}
        </div>
      ) : null}
    </div>
  );
}
