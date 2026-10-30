"use client";

import Link from "next/link";
import { ThemeLogo } from "@/components/shared/ThemeLogo";
import { usePathname } from "next/navigation";
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { authApi } from "@/lib/api";
import { useAuth, useAccessPolicy } from "@/hooks";
import { clsx } from "clsx";
import { NavBarMetrics } from "@/components/layout/NavBarMetrics";
import { CommandPalette } from "@/components/layout/CommandPalette";
import { IA_CYCLE } from "@/lib/iaCycle";
import {
  LayoutDashboard,
  Settings,
  LogOut,
  Grid,
  Microscope,
  Workflow,
  UserCircle,
  MessageCircle,
  BarChart3,
  MoreHorizontal,
  Blocks,
  Terminal,
  ArrowLeftRight,
  Shield,
  Filter,
  Globe,
  Briefcase,
  ChevronDown,
  PieChart,
  Activity,
  Bell,
  BookOpen,
  FileText,
} from "lucide-react";
import { useLocale } from "@/contexts/LocaleContext";

type NavItem = {
  id: string;
  label: string;
  href: string;
  icon: typeof LayoutDashboard;
};

/** Main sections, in the order they were before the 4 Oct cycle strip. */
const PRIMARY_ITEMS: NavItem[] = [
  { id: "dashboard", label: "Главная", href: "/", icon: LayoutDashboard },
  { id: "markets", label: "Рынки", href: "/markets", icon: Globe },
  {
    id: "direct-deals",
    label: "Сделки",
    href: "/direct-deals",
    icon: ArrowLeftRight,
  },
  { id: "chat", label: "Чат", href: "/chat", icon: MessageCircle },
  { id: "bots", label: "Боты", href: "/bots", icon: Grid },
  {
    id: "portfolio",
    label: "Портфель",
    href: "/portfolio",
    icon: PieChart,
  },
  { id: "futures", label: "Фьючерсы", href: "/futures", icon: Activity },
  {
    id: "forecasting",
    label: "Прогноз",
    href: "/forecasting",
    icon: BarChart3,
  },
  { id: "screener", label: "Скринер", href: "/screener", icon: Filter },
  {
    id: "composer",
    label: "Стратегии",
    href: "/strategy-composer",
    icon: Workflow,
  },
  { id: "platform", label: "Платформа", href: "/platform", icon: Briefcase },
];

const ACCOUNT_ITEMS: NavItem[] = [
  { id: "account", label: "Кабинет", href: "/account", icon: UserCircle },
  {
    id: "notifications",
    label: "Уведомления",
    href: "/notifications",
    icon: Bell,
  },
  { id: "settings", label: "Настройки", href: "/settings", icon: Settings },
  {
    id: "methodology",
    label: "Методика",
    href: "/methodology",
    icon: BookOpen,
  },
  { id: "documents", label: "Документы", href: "/legal", icon: FileText },
];

const TERMINAL_NAV_ITEM: NavItem = {
  id: "terminal",
  label: "Терминал",
  href: "/terminal",
  icon: Terminal,
};
const ADMISSIONS_NAV_ITEM: NavItem = {
  id: "admissions",
  label: "Допуски",
  href: "/operator/admissions",
  icon: Microscope,
};
const INTEGRATIONS_NAV_ITEM: NavItem = {
  id: "integrations",
  label: "Интеграции",
  href: "/ops/crypto-integrations",
  icon: Blocks,
};
const OPS_NAV_ITEM: NavItem = {
  id: "admin-ops",
  label: "Наблюдаемость",
  href: "/admin/ops",
  icon: Shield,
};

/** Initial inline count before measuring; afterwards it follows the real free width. */
const INLINE_NAV_COUNT = 5;

interface NavBarProps {
  activeTab?: string;
}

function useLabel() {
  const { t } = useLocale();
  return (item: NavItem) => {
    const key = `nav.${item.id}`;
    const v = t(key);
    return v === key ? item.label : v;
  };
}

function NavLink({
  item,
  isActive,
  inMenu = false,
}: {
  item: NavItem;
  isActive: boolean;
  inMenu?: boolean;
}) {
  const label = useLabel()(item);
  const { href, icon: Icon, id } = item;
  return (
    <Link
      href={href}
      title={label}
      data-tour={`nav-${id}`}
      role={inMenu ? "menuitem" : undefined}
      className={clsx(
        "flex items-center gap-1.5 rounded-md text-xs leading-none whitespace-nowrap cursor-pointer",
        inMenu ? "px-2.5 py-2 w-full" : "px-2 py-1.5 shrink-0 min-h-[36px]",
        "text-qa-muted hover:text-qa-text hover:bg-[var(--qa-hover)] transition-colors duration-150",
        "focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-terminal-accent/70",
        isActive &&
          "text-terminal-accent bg-[var(--qa-active)] border border-terminal-accent/40",
      )}
    >
      <Icon size={14} className="shrink-0" aria-hidden />
      <span>{label}</span>
    </Link>
  );
}

function NavMenu({
  id,
  label,
  icon: Icon,
  active,
  className,
  children,
}: {
  id: string;
  label: string;
  icon: typeof LayoutDashboard;
  active: boolean;
  className?: string;
  children: React.ReactNode;
}) {
  const pathname = usePathname();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => setOpen(false), [pathname]);
  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node))
        setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onDoc);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDoc);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  return (
    <div ref={ref} className={clsx("relative shrink-0", className)}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className={clsx(
          "flex items-center gap-1 px-2 py-1.5 rounded-md text-xs min-h-[36px] whitespace-nowrap transition-colors duration-150",
          active || open
            ? "text-terminal-accent bg-[var(--qa-active)] border border-terminal-accent/40"
            : "text-qa-muted hover:text-qa-text hover:bg-[var(--qa-hover)] border border-transparent",
        )}
        aria-expanded={open}
        aria-haspopup="menu"
        data-tour={`nav-${id}`}
      >
        <Icon size={14} aria-hidden />
        <span>{label}</span>
        <ChevronDown
          size={12}
          aria-hidden
          className={clsx("transition-transform", open && "rotate-180")}
        />
      </button>
      {open && (
        <div
          role="menu"
          className="absolute left-0 top-full mt-1 z-50 min-w-[220px] max-h-[70vh] overflow-y-auto rounded-lg border border-cockpit-border bg-cockpit-surface p-1.5 shadow-xl"
        >
          {children}
        </div>
      )}
    </div>
  );
}

export function NavBar({ activeTab }: NavBarProps) {
  const pathname = usePathname();
  const { isStaff, isAdmin } = useAuth();
  const { accountNavLocked } = useAccessPolicy();

  const primary = isStaff
    ? [PRIMARY_ITEMS[0], TERMINAL_NAV_ITEM, ...PRIMARY_ITEMS.slice(1)]
    : PRIMARY_ITEMS;
  // Show as many sections inline as actually fit; the rest go to «Ещё».
  // Never overlaps the right-side badges, whatever the role, zoom or width.
  const [fit, setFit] = useState(INLINE_NAV_COUNT);
  const navRef = useRef<HTMLElement>(null);
  const measureRef = useRef<HTMLDivElement>(null);
  const menusRef = useRef<HTMLDivElement>(null);
  useLayoutEffect(() => {
    const nav = navRef.current;
    if (!nav) return;
    const recompute = () => {
      const widths = Array.from(measureRef.current?.children ?? []).map(
        (el) => (el as HTMLElement).offsetWidth + 2,
      );
      const free = nav.clientWidth - (menusRef.current?.offsetWidth ?? 0) - 8;
      let used = 0;
      let n = 0;
      for (const w of widths) {
        if (used + w > free) break;
        used += w;
        n += 1;
      }
      setFit(n);
    };
    recompute();
    const ro = new ResizeObserver(recompute);
    ro.observe(nav);
    return () => ro.disconnect();
  }, [primary.length]);
  const inlineItems = primary.slice(0, fit);
  const wideItems = primary.slice(fit);
  const accountItems = ACCOUNT_ITEMS.filter(
    (item) => !(accountNavLocked && item.id === "account"),
  );
  const staffItems = isStaff
    ? [
        ADMISSIONS_NAV_ITEM,
        ...(isAdmin ? [INTEGRATIONS_NAV_ITEM, OPS_NAV_ITEM] : []),
      ]
    : [];

  const isItemActive = (id: string, href: string) => {
    const baseHref = href.split("#")[0];
    if (activeTab) {
      if (
        activeTab === "grid" ||
        activeTab === "dca-bots" ||
        activeTab === "momentum-bots"
      ) {
        return id === "bots";
      }
      return activeTab === id;
    }
    if (id === "dashboard") return pathname === "/";
    if (id === "terminal") {
      return pathname === "/terminal" || pathname.startsWith("/ops/fincept");
    }
    if (id === "bots") {
      return (
        pathname === "/bots" ||
        pathname.startsWith("/bots/") ||
        pathname === "/grid" ||
        pathname.startsWith("/grid/") ||
        pathname === "/dca-bots" ||
        pathname === "/momentum-bots"
      );
    }
    return pathname === baseHref || pathname.startsWith(`${baseHref}/`);
  };
  const anyActive = (items: NavItem[]) =>
    items.some((i) => isItemActive(i.id, i.href));

  const handleLogout = () => {
    authApi.logout();
    window.location.href = "/login";
  };

  return (
    <header className="border-b border-cockpit-border bg-cockpit-surface/95 backdrop-blur-sm px-2 xl:px-4 py-2 flex items-center justify-between shrink-0 gap-2 min-w-0 relative z-40">
      <div className="flex items-center gap-1.5 min-w-0 flex-1">
        <Link
          href="/"
          className="flex items-center gap-1.5 shrink-0"
          title="Quant Analytics"
          aria-label="Quant Analytics"
        >
          <ThemeLogo width={28} height={28} priority />
          <span className="hidden md:inline text-[11px] font-bold text-qa-text tracking-tight whitespace-nowrap">
            <span className="lg:hidden">QUANT</span>
            <span className="hidden lg:inline">QUANT ANALYTICS</span>
          </span>
        </Link>

        <nav
          ref={navRef}
          className="hidden md:flex flex-1 min-w-0 items-center gap-0.5 relative"
          aria-label="Main navigation"
          data-testid="ia-cycle-nav"
        >
          <ol className="sr-only" data-testid="ia-cycle-schema">
            {IA_CYCLE.map((group) => (
              <li key={group.id} data-cycle={group.id}>
                {group.label}: {group.items.map((item) => item.id).join(", ")}
              </li>
            ))}
          </ol>
          {inlineItems.map((item) => (
            <NavLink
              key={item.id}
              item={item}
              isActive={isItemActive(item.id, item.href)}
            />
          ))}
          <div
            ref={measureRef}
            aria-hidden
            className="absolute left-0 top-0 flex gap-0.5 invisible pointer-events-none h-0 overflow-hidden"
          >
            {primary.map((item) => (
              <NavLink key={`m-${item.id}`} item={item} isActive={false} />
            ))}
          </div>

          <div ref={menusRef} className="flex items-center gap-0.5 shrink-0">
            <NavMenu
              id="more"
              label="Ещё"
              icon={MoreHorizontal}
              active={anyActive([...wideItems, ...accountItems, ...staffItems])}
            >
              {wideItems.length > 0 && (
                <div className="py-1 border-b border-cockpit-border mb-1">
                  {wideItems.map((item) => (
                    <NavLink
                      key={item.id}
                      item={item}
                      isActive={isItemActive(item.id, item.href)}
                      inMenu
                    />
                  ))}
                </div>
              )}
              {accountItems.map((item) => (
                <NavLink
                  key={item.id}
                  item={item}
                  isActive={isItemActive(item.id, item.href)}
                  inMenu
                />
              ))}
              {staffItems.length > 0 && (
                <div className="pt-1 mt-1 border-t border-cockpit-border">
                  {staffItems.map((item) => (
                    <NavLink
                      key={item.id}
                      item={item}
                      isActive={isItemActive(item.id, item.href)}
                      inMenu
                    />
                  ))}
                </div>
              )}
            </NavMenu>
          </div>
        </nav>
      </div>

      <div className="flex items-center gap-1.5 shrink-0 min-w-0 ml-1">
        <NavBarMetrics />
        <button
          type="button"
          onClick={handleLogout}
          className="flex items-center gap-1 text-[11px] text-qa-muted hover:text-qa-text transition-colors shrink-0"
          aria-label="Выйти"
        >
          <LogOut size={12} />
          <span className="hidden xl:inline">Выйти</span>
        </button>
      </div>
      <CommandPalette />
    </header>
  );
}
