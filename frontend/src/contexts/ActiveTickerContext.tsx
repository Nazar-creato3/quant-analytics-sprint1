"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import {
  DEFAULT_ACTIVE_TICKER,
  normalizeActiveTicker,
  readStoredActiveTicker,
  writeStoredActiveTicker,
} from "@/lib/active-ticker";

export type SetActiveTickerOptions = {
  /** When false, persist ticker but do not rewrite the current URL (e.g. leaving /screener). */
  syncUrl?: boolean;
};

interface ActiveTickerContextValue {
  activeTicker: string;
  setActiveTicker: (ticker: string, opts?: SetActiveTickerOptions) => void;
}

const ActiveTickerContext = createContext<ActiveTickerContextValue | null>(null);

const URL_SYNC_PATHS = new Set(["/terminal", "/forecasting", "/"]);

export function ActiveTickerProvider({ children }: { children: ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const urlSymbol = searchParams.get("symbol") || searchParams.get("ticker");

  const [activeTicker, setTickerState] = useState<string>(() => {
    if (urlSymbol) return normalizeActiveTicker(urlSymbol);
    return DEFAULT_ACTIVE_TICKER;
  });

  useEffect(() => {
    if (urlSymbol) {
      const next = normalizeActiveTicker(urlSymbol);
      setTickerState(next);
      writeStoredActiveTicker(next);
      return;
    }
    setTickerState(readStoredActiveTicker());
  }, [urlSymbol]);

  const setActiveTicker = useCallback(
    (ticker: string, opts?: SetActiveTickerOptions) => {
      const next = normalizeActiveTicker(ticker);
      setTickerState(next);
      writeStoredActiveTicker(next);
      if (opts?.syncUrl === false) return;
      if (URL_SYNC_PATHS.has(pathname)) {
        const params = new URLSearchParams(searchParams.toString());
        params.set("symbol", next);
        const qs = params.toString();
        router.replace(qs ? `${pathname}?${qs}` : pathname, { scroll: false });
      }
    },
    [pathname, router, searchParams],
  );

  const value = useMemo(
    () => ({ activeTicker, setActiveTicker }),
    [activeTicker, setActiveTicker],
  );

  return <ActiveTickerContext.Provider value={value}>{children}</ActiveTickerContext.Provider>;
}

export function useActiveTicker(): ActiveTickerContextValue {
  const ctx = useContext(ActiveTickerContext);
  if (!ctx) {
    throw new Error("useActiveTicker must be used within ActiveTickerProvider");
  }
  return ctx;
}
