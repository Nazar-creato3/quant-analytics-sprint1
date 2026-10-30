"use client";

import { useState, useEffect, useRef, useCallback } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { authApi, pipelineApi, opsApi, systemApi, accessPolicyApi } from "@/lib/api";
import { syncAuthFromCookie } from "@/lib/auth-sync";
import { countPendingTradeableManeuvers, countTradeableManeuvers, pipelineToastBackfillHint } from "@/lib/maneuvers";
import { extractErrorMessage } from "@/lib/errors";
import { User, HealthStatus, ManeuverReport, PipelineRunResponse } from "@/types";

// ── useAuth ───────────────────────────────────────────────────────────────────

function readAuthCookie(): string | null {
  if (typeof document === "undefined") return null;
  const match = document.cookie.match(/(?:^|; )access_token=([^;]*)/);
  return match ? decodeURIComponent(match[1]) : null;
}

function hasStoredAuthToken(): boolean {
  if (typeof window === "undefined") return false;
  syncAuthFromCookie();
  return Boolean(localStorage.getItem("access_token") || readAuthCookie());
}

export function useAuth() {
  const queryClient = useQueryClient();
  const [authReady, setAuthReady] = useState(false);
  const [hasToken, setHasToken] = useState(false);

  useEffect(() => {
    setHasToken(hasStoredAuthToken());
    setAuthReady(true);
  }, []);

  const {
    data: user,
    isLoading,
    error,
  } = useQuery<User>({
    queryKey: ["me"],
    queryFn: authApi.me,
    enabled: authReady && hasToken,
    retry: false,
    staleTime: 5 * 60_000, // 5 minutes
  });

  const logout = useCallback(() => {
    authApi.logout();
    queryClient.clear();
    window.location.href = "/login";
  }, [queryClient]);

  const isAuthenticated = !!user && !error;
  /** Admin / owner / system admin — Integrations Hub and similar ops surfaces. */
  const isAdmin = isAdminRole(user?.role);
  const isStaff = isAdmin || user?.role === "analyst";

  return { user, isLoading, isAuthenticated, isAdmin, isStaff, logout };
}

/** Match legacy + RBAC admin names used across the product. */
export function isAdminRole(role?: string | null): boolean {
  const r = (role || "").toLowerCase().trim();
  return (
    r === "admin" ||
    r === "owner" ||
    r === "owner_admin" ||
    r === "system_admin" ||
    r === "system-admin" ||
    r === "systemadmin"
  );
}

const FULL_ACCESS_LEVELS = new Set([
  "approved_live",
  "restricted_live",
  "managed_account",
  "enterprise",
]);

export function hasFullAccess(policy: {
  paid?: boolean;
  subscription_status?: string;
  show_trial_timer?: boolean;
  access_level?: string;
} | null | undefined, level?: string | null): boolean {
  if (!policy && !level) return false;
  if (policy?.paid || policy?.subscription_status === "paid") return true;
  if (policy?.show_trial_timer === false && FULL_ACCESS_LEVELS.has(String(policy?.access_level || level || ""))) {
    return true;
  }
  return FULL_ACCESS_LEVELS.has(String(level || policy?.access_level || ""));
}

export function useAccessPolicy() {
  const { isAuthenticated, isStaff } = useAuth();
  const { data, isLoading } = useQuery({
    queryKey: ["access-policy"],
    queryFn: accessPolicyApi.me,
    enabled: isAuthenticated,
    staleTime: 60_000,
  });
  const level = (data?.access_level as string | undefined) ?? null;
  const isTrialReadOnly = level === "trial_read_only";
  const accountNavLocked = (level === "expired" || level === "locked") && !isStaff;
  const fullAccess = hasFullAccess(data, level);
  return { level, isTrialReadOnly, accountNavLocked, isLoading, policy: data, fullAccess };
}

function pipelineFailureMessage(message: string): string {
  const m = message.toLowerCase();
  if (
    m.includes("sigkill") ||
    m.includes("signal 9") ||
    m.includes("exited prematurely") ||
    m.includes("worker lost")
  ) {
    return "Сервер анализа исчерпал память (сервис перезапущен). Подождите минуту и повторите «Подобрать манёвры».";
  }
  return message;
}

function isRetryablePipelinePollError(err: unknown): boolean {
  const status = (err as { response?: { status?: number } })?.response?.status;
  if (status == null) return true;
  return status >= 500 || status === 429 || status === 408;
}

// ── usePipelineRun ────────────────────────────────────────────────────────────

async function fetchReportWithRetry(reportId: string, attempts = 4): Promise<ManeuverReport> {
  let lastErr: unknown;
  for (let i = 0; i < attempts; i += 1) {
    try {
      return await pipelineApi.getReport(reportId);
    } catch (err) {
      lastErr = err;
      if (i < attempts - 1) {
        await new Promise(r => setTimeout(r, 400 * (i + 1)));
      }
    }
  }
  throw lastErr;
}

async function resolveReportForPipelineRun(runId: string): Promise<{
  reportId: string;
  report: ManeuverReport;
} | null> {
  try {
    const page = await pipelineApi.listReports(1, 15);
    const match = page.items.find(r => r.pipeline_run_id === runId);
    if (!match?.id) return null;
    const report = await fetchReportWithRetry(match.id);
    return { reportId: match.id, report };
  } catch {
    return null;
  }
}

interface PipelineRunOptions {
  onComplete?: (
    reportId: string,
    stats?: {
      tradeable_count?: number | null;
      pending_approval_count?: number | null;
      maneuver_slots?: number | null;
      report?: ManeuverReport;
      backfill_hint?: ReturnType<typeof pipelineToastBackfillHint>;
    },
  ) => void;
  onError?: (message: string) => void;
  /** Use ops/run-market-analysis (effective watchlist) vs pipeline/run */
  useOpsEndpoint?: boolean;
}

export function usePipelineRun(options?: PipelineRunOptions) {
  const queryClient = useQueryClient();
  const [runId, setRunId] = useState<string | null>(null);
  const [status, setStatus] = useState<string>("idle");
  const [lastError, setLastError] = useState<string | null>(null);
  const [elapsedSec, setElapsedSec] = useState(0);
  const pollingRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const pollStartedAtRef = useRef<number | null>(null);
  const unknownPollsRef = useRef(0);
  const pollErrorsRef = useRef(0);
  const inFlightPollRef = useRef(false);

  const POLL_INTERVAL_MS = 3_000;
  // Same as the server-side run expiry (pipeline_dispatch._RUN_EXPIRES_SEC = 900):
  // on a loaded server a run takes 5-7 min, and giving up at 6 min hid finished reports.
  const POLL_TIMEOUT_MS = 900_000;
  const SLOW_RUN_SEC = 45;
  const EARLY_RECOVERY_SEC = 40;
  const UNKNOWN_RECOVERY_EVERY = 5;
  const MAX_UNKNOWN_POLLS = 25;
  const MAX_POLL_ERRORS = 6;

  const clearPolling = () => {
    if (pollingRef.current) {
      clearTimeout(pollingRef.current);
      pollingRef.current = null;
    }
    pollStartedAtRef.current = null;
    unknownPollsRef.current = 0;
    pollErrorsRef.current = 0;
    inFlightPollRef.current = false;
    setElapsedSec(0);
  };

  const finishWithReport = useCallback(
    async (id: string, resp: PipelineRunResponse) => {
      let reportId = resp.report_id ?? null;
      let tradeable = resp.tradeable_count ?? 0;
      let slots = resp.maneuver_slots;
      let report: ManeuverReport | undefined;

      const hydrateReport = async (rid: string) => {
        report = await fetchReportWithRetry(rid);
        queryClient.setQueryData(["decision-feed-latest-report", rid], report);
        queryClient.setQueryData(["report", rid], report);
        tradeable = countTradeableManeuvers(report.maneuvers);
        const ctx = report.market_context as { maneuver_slots?: number } | undefined;
        slots = ctx?.maneuver_slots ?? slots;
      };

      if (reportId) {
        try {
          await hydrateReport(reportId);
        } catch {
          const recovered = await resolveReportForPipelineRun(id);
          if (recovered) {
            reportId = recovered.reportId;
            report = recovered.report;
            queryClient.setQueryData(["decision-feed-latest-report", reportId], report);
            queryClient.setQueryData(["report", reportId], report);
            tradeable = countTradeableManeuvers(report.maneuvers);
          }
        }
      } else {
        const recovered = await resolveReportForPipelineRun(id);
        if (recovered) {
          reportId = recovered.reportId;
          report = recovered.report;
          queryClient.setQueryData(["decision-feed-latest-report", reportId], report);
          queryClient.setQueryData(["report", reportId], report);
          tradeable = countTradeableManeuvers(report.maneuvers);
        }
      }

      if (reportId) {
        const pendingApproval = report
          ? countPendingTradeableManeuvers(report.maneuvers)
          : 0;
        options?.onComplete?.(reportId, {
          tradeable_count: report ? tradeable : 0,
          pending_approval_count: pendingApproval,
          maneuver_slots: slots,
          report,
          backfill_hint: report ? pipelineToastBackfillHint(report) : null,
        });
      } else {
        options?.onError?.(
          "Анализ завершён, но отчёт не найден — обновите страницу или запустите снова",
        );
      }

      queryClient.invalidateQueries({ queryKey: ["decision-feed-reports"] });
      queryClient.invalidateQueries({ queryKey: ["reports"] });
      queryClient.invalidateQueries({ queryKey: ["decision-feed-pending-maneuvers"] });
      queryClient.invalidateQueries({ queryKey: ["pending-approvals"] });
      queryClient.invalidateQueries({ queryKey: ["portfolio-metrics"] });
    },
    [options, queryClient],
  );

  const failRun = useCallback(
    (message: string) => {
      clearPolling();
      setRunId(null);
      setStatus("failed");
      const friendly = pipelineFailureMessage(message);
      setLastError(friendly);
      options?.onError?.(friendly);
    },
    [options],
  );

  const pollOnceRef = useRef<(id: string) => Promise<void>>(async () => {});

  pollOnceRef.current = async (id: string) => {
    if (inFlightPollRef.current) {
      pollingRef.current = setTimeout(() => {
        void pollOnceRef.current(id);
      }, POLL_INTERVAL_MS);
      return;
    }
    inFlightPollRef.current = true;
    try {
      const startedAt = pollStartedAtRef.current;
      if (startedAt != null) {
        setElapsedSec(Math.floor((Date.now() - startedAt) / 1000));
      }
      if (startedAt != null && Date.now() - startedAt > POLL_TIMEOUT_MS) {
        const recovered = await resolveReportForPipelineRun(id);
        if (recovered) {
          clearPolling();
          setRunId(null);
          setStatus("complete");
          await finishWithReport(id, {
            run_id: id,
            status: "complete",
            report_id: recovered.reportId,
          } as PipelineRunResponse);
          return;
        }
        failRun(
          "Подбор манёвров не уложился в 15 минут. Повторите позже.",
        );
        return;
      }

      const resp = await pipelineApi.pollStatus(id);
      pollErrorsRef.current = 0;
      setStatus(resp.status);

      if (
        startedAt != null &&
        Date.now() - startedAt > EARLY_RECOVERY_SEC &&
        (resp.status === "started" || resp.status === "progress" || resp.status === "success")
      ) {
        const recovered = await resolveReportForPipelineRun(id);
        if (recovered) {
          clearPolling();
          setRunId(null);
          setStatus("complete");
          await finishWithReport(id, {
            run_id: id,
            status: "complete",
            report_id: recovered.reportId,
          } as PipelineRunResponse);
          return;
        }
      }

      const terminalStale =
        resp.message?.includes("worker не обрабатывает") ||
        resp.message?.includes("worker ran out of memory");

      if (resp.status === "unknown") {
        unknownPollsRef.current += 1;
        if (unknownPollsRef.current % UNKNOWN_RECOVERY_EVERY === 0) {
          const recovered = await resolveReportForPipelineRun(id);
          if (recovered) {
            clearPolling();
            setRunId(null);
            setStatus("complete");
            await finishWithReport(id, {
              run_id: id,
              status: "complete",
              report_id: recovered.reportId,
            } as PipelineRunResponse);
            return;
          }
        }
        if (unknownPollsRef.current >= MAX_UNKNOWN_POLLS) {
          failRun("Не удалось отследить анализ — worker не ответил. Повторите через минуту.");
          return;
        }
      } else {
        unknownPollsRef.current = 0;
      }

      if (resp.status === "complete") {
        if (!resp.report_id) {
          const recovered = await resolveReportForPipelineRun(id);
          if (recovered) {
            clearPolling();
            setRunId(null);
            await finishWithReport(id, {
              ...resp,
              report_id: recovered.reportId,
            });
            return;
          }
          failRun(resp.message ?? "Анализ завершён без отчёта — повторите через минуту");
          return;
        }
        clearPolling();
        setRunId(null);
        await finishWithReport(id, resp);
        return;
      }
      if (resp.status === "failed" || terminalStale) {
        failRun(resp.message ?? "Pipeline failed");
        return;
      }

      pollingRef.current = setTimeout(() => {
        void pollOnceRef.current(id);
      }, POLL_INTERVAL_MS);
    } catch (err) {
      pollErrorsRef.current += 1;
      const detail = extractErrorMessage(err, "Не удалось получить статус pipeline");
      if (
        pollErrorsRef.current < MAX_POLL_ERRORS &&
        isRetryablePipelinePollError(err)
      ) {
        pollingRef.current = setTimeout(() => {
          void pollOnceRef.current(id);
        }, POLL_INTERVAL_MS * 2);
        return;
      }
      failRun(detail);
    } finally {
      inFlightPollRef.current = false;
    }
  };

  const startPolling = useCallback((id: string) => {
    clearPolling();
    pollStartedAtRef.current = Date.now();
    void pollOnceRef.current(id);
  }, []);

  const trigger = useMutation({
    mutationFn: async (watchlist?: string[]) => {
      if (options?.useOpsEndpoint !== false) {
        const resp = await opsApi.runMarketAnalysis();
        if (!resp.run_id) {
          throw new Error(resp.message ?? "Не удалось запустить анализ рынка");
        }
        return {
          run_id: resp.run_id,
          task_id: resp.task_id,
          status: resp.status,
        };
      }
      return pipelineApi.run(watchlist);
    },
    onSuccess: (resp) => {
      setLastError(null);
      const runId = resp.run_id?.trim();
      if (!runId) {
        setStatus("error");
        setLastError("Сервер не ответил — нажмите «Подобрать манёвры» ещё раз");
        return;
      }
      setRunId(runId);
      setStatus(resp.status ?? "queued");
      startPolling(runId);
    },
    onError: (err) => {
      setStatus("error");
      const msg = extractErrorMessage(err, "Не удалось запустить анализ рынка");
      setLastError(msg);
      options?.onError?.(msg);
    },
  });

  useEffect(() => () => clearPolling(), []);

  return {
    trigger: trigger.mutate,
    isRunning: trigger.isPending || !!runId,
    status,
    runId,
    lastError,
    elapsedSec,
    slowRun: elapsedSec >= SLOW_RUN_SEC,
  };
}

// ── usePolling ────────────────────────────────────────────────────────────────

export function usePolling<T>(
  fetcher: () => Promise<T>,
  intervalMs: number,
  enabled = true,
) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<Error | null>(null);
  const timerRef = useRef<NodeJS.Timeout | null>(null);

  const fetch = useCallback(async () => {
    try {
      const result = await fetcher();
      setData(result);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err : new Error(String(err)));
    }
  }, [fetcher]);

  useEffect(() => {
    if (!enabled) return;
    fetch();
    timerRef.current = setInterval(fetch, intervalMs);
    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, [enabled, intervalMs, fetch]);

  return { data, error };
}

// ── useHealth ─────────────────────────────────────────────────────────────────

export function useHealth() {
  return useQuery<HealthStatus>({
    queryKey: ["health"],
    queryFn: systemApi.health,
    refetchInterval: 30_000,
    staleTime: 15_000,
  });
}

// ── useDebounce ───────────────────────────────────────────────────────────────

export function useDebounce<T>(value: T, delay: number): T {
  const [debounced, setDebounced] = useState(value);

  useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), delay);
    return () => clearTimeout(timer);
  }, [value, delay]);

  return debounced;
}

// ── useLocalStorage ───────────────────────────────────────────────────────────

export function useLocalStorage<T>(
  key: string,
  initialValue: T,
): [T, (value: T) => void] {
  const [storedValue, setStoredValue] = useState<T>(() => {
    if (typeof window === "undefined") return initialValue;
    try {
      const item = localStorage.getItem(key);
      return item ? JSON.parse(item) : initialValue;
    } catch {
      return initialValue;
    }
  });

  const setValue = useCallback(
    (value: T) => {
      try {
        setStoredValue(value);
        if (typeof window !== "undefined") {
          localStorage.setItem(key, JSON.stringify(value));
        }
      } catch (error) {
        console.error("useLocalStorage write failed:", error);
      }
    },
    [key],
  );

  return [storedValue, setValue];
}

// ── useDashboardMode ──────────────────────────────────────────────────────────

export type { DashboardMode } from "@/lib/dashboard-mode";
export { DASHBOARD_MODE_KEY, resetDashboardMode } from "@/lib/dashboard-mode";

import { type DashboardMode } from "@/lib/dashboard-mode";
import { useDashboardModeContext } from "@/contexts/DashboardModeContext";

/** Shared dashboard mode via React context + URL ?mode= on home page. */
export function useDashboardMode(): [DashboardMode, (mode: DashboardMode) => void] {
  const { mode, setMode } = useDashboardModeContext();
  return [mode, setMode];
}

export { useChartColors } from "./useChartColors";
export { useEffectiveWatchlist, WATCHLIST_QUERY_KEY, FALLBACK_WATCHLIST } from "./useEffectiveWatchlist";
