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
  type DashboardMode,
  isDashboardMode,
  readDashboardMode,
  writeDashboardMode,
} from "@/lib/dashboard-mode";

interface DashboardModeContextValue {
  mode: DashboardMode;
  setMode: (mode: DashboardMode) => void;
}

const DashboardModeContext = createContext<DashboardModeContextValue | null>(null);

export function DashboardModeProvider({ children }: { children: ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const urlMode = searchParams.get("mode");

  const [mode, setModeState] = useState<DashboardMode>(() => {
    if (isDashboardMode(urlMode)) return urlMode;
    return "operator";
  });

  // Hydrate from URL or sessionStorage on mount / URL change.
  useEffect(() => {
    if (isDashboardMode(urlMode)) {
      setModeState(urlMode);
      writeDashboardMode(urlMode);
      return;
    }
    if (pathname === "/") {
      setModeState(readDashboardMode());
    }
  }, [urlMode, pathname]);

  const setMode = useCallback(
    (next: DashboardMode) => {
      setModeState(next);
      writeDashboardMode(next);
      if (pathname === "/") {
        const params = new URLSearchParams(searchParams.toString());
        params.set("mode", next);
        router.replace(`/?${params.toString()}`, { scroll: false });
      }
    },
    [pathname, router, searchParams],
  );

  const value = useMemo(() => ({ mode, setMode }), [mode, setMode]);

  return (
    <DashboardModeContext.Provider value={value}>{children}</DashboardModeContext.Provider>
  );
}

export function useDashboardModeContext(): DashboardModeContextValue {
  const ctx = useContext(DashboardModeContext);
  if (!ctx) {
    throw new Error("useDashboardModeContext must be used within DashboardModeProvider");
  }
  return ctx;
}
