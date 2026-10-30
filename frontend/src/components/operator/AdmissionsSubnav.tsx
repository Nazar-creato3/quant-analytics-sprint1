"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { clsx } from "clsx";
import { useAuth } from "@/hooks";

const ITEMS: Array<{
  href: string;
  label: string;
  exact: boolean;
  admin?: boolean;
}> = [
  { href: "/operator/admissions", label: "Клиенты", exact: true },
  { href: "/operator/admissions/accounts", label: "Счета", admin: true, exact: false },
];

export function AdmissionsSubnav() {
  const pathname = usePathname();
  const { isAdmin } = useAuth();

  return (
    <nav className="inline-flex rounded border border-cockpit-border overflow-hidden shrink-0">
      {ITEMS.filter((item) => !item.admin || isAdmin).map((item) => {
        const active = item.exact
          ? pathname === item.href
          : pathname === item.href || pathname.startsWith(`${item.href}/`);
        return (
          <Link
            key={item.href}
            href={item.href}
            className={clsx(
              "text-xs px-3 py-1.5",
              item.href !== ITEMS[0].href && "border-l border-cockpit-border",
              active
                ? "bg-[var(--qa-active)] text-terminal-accent"
                : "text-qa-muted hover:bg-cockpit-panel-raised/40",
            )}
          >
            {item.label}
          </Link>
        );
      })}
    </nav>
  );
}
