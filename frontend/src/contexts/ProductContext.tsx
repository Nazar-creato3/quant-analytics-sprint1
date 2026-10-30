"use client";

import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useActiveTicker } from "@/contexts/ActiveTickerContext";

export type BookMode = "paper" | "live";
export type DisplayCurrency = "RUB" | "USD";
export type DisplayPeriod = "1d" | "1w" | "1m" | "ytd" | "inception";

type ProductContextValue = {
  activeTicker: string;
  setActiveTicker: (ticker: string) => void;
  activeAccount: string;
  setActiveAccount: (id: string) => void;
  mode: BookMode;
  setMode: (mode: BookMode) => void;
  period: DisplayPeriod;
  setPeriod: (period: DisplayPeriod) => void;
  currency: DisplayCurrency;
  setCurrency: (currency: DisplayCurrency) => void;
};

const ProductContext = createContext<ProductContextValue | null>(null);

const ACCOUNT_KEY = "qa.activeAccount";
const MODE_KEY = "qa.bookMode";
const PERIOD_KEY = "qa.period";
const CURRENCY_KEY = "qa.currency";

function read<T extends string>(key: string, fallback: T, allowed: readonly T[]): T {
  if (typeof window === "undefined") return fallback;
  const raw = window.localStorage.getItem(key);
  return raw && (allowed as readonly string[]).includes(raw) ? (raw as T) : fallback;
}

export function ProductProvider({ children }: { children: ReactNode }) {
  const { activeTicker, setActiveTicker } = useActiveTicker();
  const queryClient = useQueryClient();
  const [activeAccount, setAccountState] = useState(() =>
    typeof window === "undefined" ? "demo" : window.localStorage.getItem(ACCOUNT_KEY) || "demo",
  );
  const [mode, setModeState] = useState<BookMode>(() => read(MODE_KEY, "paper", ["paper", "live"]));
  const [period, setPeriodState] = useState<DisplayPeriod>(() =>
    read(PERIOD_KEY, "1m", ["1d", "1w", "1m", "ytd", "inception"]),
  );
  const [currency, setCurrencyState] = useState<DisplayCurrency>(() =>
    read(CURRENCY_KEY, "RUB", ["RUB", "USD"]),
  );

  const setActiveAccount = useCallback((id: string) => {
    const next = id.trim() || "demo";
    setAccountState(next);
    window.localStorage.setItem(ACCOUNT_KEY, next);
  }, []);

  const setMode = useCallback(
    (next: BookMode) => {
      setModeState(next);
      window.localStorage.setItem(MODE_KEY, next);
      // Several queries read the mode at call time (header capital, positions):
      // refetch everything so the screen switches books at once.
      void queryClient.invalidateQueries();
    },
    [queryClient],
  );

  const setPeriod = useCallback((next: DisplayPeriod) => {
    setPeriodState(next);
    window.localStorage.setItem(PERIOD_KEY, next);
  }, []);

  const setCurrency = useCallback((next: DisplayCurrency) => {
    setCurrencyState(next);
    window.localStorage.setItem(CURRENCY_KEY, next);
  }, []);

  const value = useMemo(
    () => ({
      activeTicker,
      setActiveTicker,
      activeAccount,
      setActiveAccount,
      mode,
      setMode,
      period,
      setPeriod,
      currency,
      setCurrency,
    }),
    [activeTicker, setActiveTicker, activeAccount, setActiveAccount, mode, setMode, period, setPeriod, currency, setCurrency],
  );

  return <ProductContext.Provider value={value}>{children}</ProductContext.Provider>;
}

export function useProductContext(): ProductContextValue {
  const ctx = useContext(ProductContext);
  if (!ctx) {
    throw new Error("useProductContext must be used within ProductProvider");
  }
  return ctx;
}
