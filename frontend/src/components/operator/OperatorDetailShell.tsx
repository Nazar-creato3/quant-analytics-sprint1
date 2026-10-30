"use client";

import Link from "next/link";
import { ArrowLeft } from "lucide-react";
import { NavBar } from "@/components/layout/NavBar";

interface OperatorDetailShellProps {
  title: string;
  description?: string;
  backHref?: string;
  /** When true, main area fills viewport with internal scroll (kanban, watchlist, feeds). */
  fillViewport?: boolean;
  children: React.ReactNode;
}

export function OperatorDetailShell({
  title,
  description,
  backHref = "/",
  fillViewport = false,
  children,
}: OperatorDetailShellProps) {
  return (
    <div className="h-[calc(100dvh-3.5rem)] md:h-[calc(100dvh-3.5rem)] overflow-hidden bg-cockpit-bg text-qa-text flex flex-col operator-shell">
      <NavBar />
      <div className="border-b border-cockpit-border bg-cockpit-surface px-4 py-3 shrink-0">
        <Link
          href={backHref}
          className="inline-flex items-center gap-1.5 text-xs text-qa-muted hover:text-qa-text mb-2"
        >
          <ArrowLeft size={12} />
          Панель оператора
        </Link>
        <h1 className="text-sm font-semibold text-white">{title}</h1>
        {description && (
          <p className="text-xs text-qa-muted mt-1">{description}</p>
        )}
      </div>
      <main
        className={
          fillViewport
            ? "flex-1 flex flex-col min-h-0 overflow-hidden p-4"
            : "flex-1 overflow-auto p-4"
        }
      >
        {children}
      </main>
    </div>
  );
}
