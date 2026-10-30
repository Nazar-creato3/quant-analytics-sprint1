"use client";

import type { ReactNode } from "react";
import { clsx } from "clsx";
import { BackButton } from "@/components/layout/BackButton";

type AppPageShellWidth = "md" | "lg" | "xl" | "full";

const WIDTH_CLASS: Record<AppPageShellWidth, string> = {
  md: "max-w-3xl",
  lg: "max-w-5xl",
  xl: "max-w-6xl",
  full: "max-w-[1600px]",
};

interface AppPageShellProps {
  title: string;
  description?: string;
  children: ReactNode;
  width?: AppPageShellWidth;
  /** When true, main grows to fill viewport below NavBar (chat-style). */
  fillViewport?: boolean;
  className?: string;
  headerExtra?: ReactNode;
  /** Show «Назад» above the title (default true). */
  showBack?: boolean;
}

export function AppPageShell({
  title,
  description,
  children,
  width = "lg",
  fillViewport = false,
  className,
  headerExtra,
  showBack = true,
}: AppPageShellProps) {
  return (
    <main
      className={clsx(
        "w-full mx-auto px-4 sm:px-6 py-5 lg:py-6",
        WIDTH_CLASS[width],
        fillViewport && "flex-1 flex flex-col min-h-0",
        className,
      )}
    >
      <header className="mb-5 flex flex-col gap-1 sm:flex-row sm:items-end sm:justify-between shrink-0">
        <div>
          {showBack ? <BackButton className="mb-2" /> : null}
          <h1 className="text-xl font-semibold tracking-tight text-qa-text">{title}</h1>
          {description ? (
            <p className="text-sm text-qa-muted mt-1 max-w-2xl">{description}</p>
          ) : null}
        </div>
        {headerExtra ? <div className="shrink-0">{headerExtra}</div> : null}
      </header>
      <div className={clsx("space-y-6", fillViewport && "flex-1 flex flex-col min-h-0")}>
        {children}
      </div>
    </main>
  );
}
