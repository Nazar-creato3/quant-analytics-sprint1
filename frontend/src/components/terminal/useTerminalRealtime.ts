"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { mergeTerminalSnapshot, terminalApi } from "@/lib/terminal-api";
import type { TerminalAlert, TerminalChartSeries, TerminalSnapshot, TerminalWsMessage } from "@/types/terminal";
import { useResilientWebSocket } from "@/hooks/useResilientWebSocket";
import { useDocumentVisibility } from "@/hooks/useDocumentVisibility";
import {
  freshnessFromTimestamp,
  useFreshnessClock,
  type DataFreshnessState,
} from "@/hooks/useLiveFreshness";
import { DEFAULT_ACTIVE_TICKER } from "@/lib/active-ticker";

const QUERY_KEY = ["terminal", "snapshot"] as const;
const POLL_MS = 60_000;
const STALE_POLL_MS = 30_000;

function liveLog(event: string, detail?: unknown) {
  // eslint-disable-next-line no-console
  console.info(`[live-terminal] ${new Date().toISOString()} ${event}`, detail ?? "");
}

function wsBaseUrl(): string {
  if (typeof window === "undefined") return "";
  const configured = process.env.NEXT_PUBLIC_API_URL?.trim();
  const origin =
    configured ||
    (window.location.hostname === "localhost" ? "http://localhost:8000" : window.location.origin);
  return origin.replace(/^http/, "ws").replace(/\/$/, "");
}

function snapshotLooksEnriched(snap: TerminalSnapshot | null | undefined): boolean {
  if (!snap) return false;
  const idxOk = snap.indices.some((i) => i.price != null);
  const watchOk = snap.watchlist.some((w) => Boolean(w.symbol?.trim()) && w.last != null);
  return idxOk || watchOk || (snap.news?.length ?? 0) > 0 || snap.pulse?.fear_greed != null;
}

function isTerminalDataMessage(msg: Record<string, unknown>): boolean {
  const type = String(msg.type ?? "");
  return type === "tick" || type === "snapshot" || type === "alert";
}

export function useTerminalRealtime() {
  const qc = useQueryClient();
  const [liveAlerts, setLiveAlerts] = useState<TerminalAlert[]>([]);
  const [lastPollAt, setLastPollAt] = useState<number | null>(null);
  const [enrichmentDeadlinePassed, setEnrichmentDeadlinePassed] = useState(false);
  const fetchGen = useRef(0);

  const buildUrl = useCallback(() => {
    if (typeof window === "undefined") return null;
    const token = localStorage.getItem("access_token");
    const qs = token ? `?token=${encodeURIComponent(token)}` : "";
    return `${wsBaseUrl()}/api/v1/ws/terminal${qs}`;
  }, []);

  const handleWsMessage = useCallback(
    (msg: Record<string, unknown>) => {
      const typed = msg as TerminalWsMessage & { type: string; data?: unknown };
      if (typed.type === "tick" || typed.type === "snapshot") {
        liveLog("ws_data", { type: typed.type });
      }
      if (typed.type === "snapshot" && typed.data && typeof typed.data === "object") {
        qc.setQueryData(QUERY_KEY, (prev: TerminalSnapshot | undefined) =>
          mergeTerminalSnapshot(prev, typed.data as Partial<TerminalSnapshot> & Record<string, unknown>, {
            mode: "full",
          }),
        );
      } else if (typed.type === "tick" && typed.data && typeof typed.data === "object") {
        qc.setQueryData(QUERY_KEY, (prev: TerminalSnapshot | undefined) =>
          mergeTerminalSnapshot(prev, typed.data as Partial<TerminalSnapshot> & Record<string, unknown>, {
            mode: "patch",
          }),
        );
      } else if (typed.type === "alert" && typed.data) {
        setLiveAlerts((a) => [typed.data as TerminalAlert, ...a].slice(0, 20));
        qc.setQueryData(QUERY_KEY, (prev: TerminalSnapshot | undefined) =>
          prev
            ? {
                ...prev,
                alerts: [typed.data as TerminalAlert, ...prev.alerts].slice(0, 30),
              }
            : prev,
        );
      }
    },
    [qc],
  );

  const { connectionState, lastDataAt, lastMessageAt } = useResilientWebSocket({
    buildUrl,
    label: "terminal",
    isDataMessage: isTerminalDataMessage,
    onMessage: handleWsMessage,
  });

  const wsConnected = connectionState === "live" || connectionState === "stale";

  const tabVisible = useDocumentVisibility();

  const snapshotQ = useQuery({
    queryKey: QUERY_KEY,
    queryFn: async () => {
      const gen = ++fetchGen.current;
      try {
        const snap = await terminalApi.snapshot();
        setLastPollAt(Date.now());
        liveLog("poll_ok", { as_of: snap.as_of, source: snap.source });
        if (gen !== fetchGen.current) {
          const prev = qc.getQueryData<TerminalSnapshot>(QUERY_KEY);
          return prev ? mergeTerminalSnapshot(prev, snap, { mode: "full" }) : snap;
        }
        const prev = qc.getQueryData<TerminalSnapshot>(QUERY_KEY);
        return mergeTerminalSnapshot(prev, snap, { mode: "full" });
      } catch (err) {
        liveLog("poll_fail", err);
        throw err;
      }
    },
    refetchInterval: (query) => {
      if (!tabVisible) return false;
      const updated = query.state.dataUpdatedAt;
      if (updated > 0 && Date.now() - updated > STALE_POLL_MS) {
        return STALE_POLL_MS;
      }
      return POLL_MS;
    },
    refetchIntervalInBackground: false,
    staleTime: 30_000,
    retry: 1,
    placeholderData: (prev) => prev,
  });

  const now = useFreshnessClock();
  const lastUpdateAt = lastDataAt ?? lastPollAt;
  const dataFreshness: DataFreshnessState = freshnessFromTimestamp(lastUpdateAt, now);

  const lastStalePollAtRef = useRef(0);
  const prevFreshnessRef = useRef(dataFreshness);

  // Force poll when WS data goes stale — throttle to avoid invalidate storms.
  useEffect(() => {
    const prev = prevFreshnessRef.current;
    prevFreshnessRef.current = dataFreshness;

    if (dataFreshness !== "stale" && dataFreshness !== "disconnected") return;

    const now = Date.now();
    const transitioned =
      prev !== dataFreshness &&
      (dataFreshness === "stale" || dataFreshness === "disconnected");
    const throttled = now - lastStalePollAtRef.current >= 30_000;
    if (!transitioned && !throttled) return;

    lastStalePollAtRef.current = now;
    liveLog("stale_fallback_poll", { state: dataFreshness, transitioned });
    void qc.invalidateQueries({ queryKey: QUERY_KEY });
  }, [dataFreshness, qc]);

  // Hard stop: never keep the Terminal spinner past 30s waiting for enrichment.
  useEffect(() => {
    setEnrichmentDeadlinePassed(false);
    const t = window.setTimeout(() => setEnrichmentDeadlinePassed(true), 30_000);
    return () => window.clearTimeout(t);
  }, []);

  const refresh = useCallback(() => {
    fetchGen.current += 1;
    setEnrichmentDeadlinePassed(false);
    window.setTimeout(() => setEnrichmentDeadlinePassed(true), 30_000);
    void qc.invalidateQueries({ queryKey: QUERY_KEY });
  }, [qc]);

  const data = snapshotQ.data ?? null;
  // Show partial ASAP — do NOT block the whole page on change_pct / open circuits.
  const waitingForEnrichment =
    !enrichmentDeadlinePassed &&
    (snapshotQ.isLoading || snapshotQ.isFetching) &&
    !data &&
    !snapshotLooksEnriched(data);

  return {
    snapshot: data,
    isLoading: (snapshotQ.isLoading && !data) || waitingForEnrichment,
    isFetching: snapshotQ.isFetching,
    error: snapshotQ.error,
    source: data?.source ?? "mock",
    wsConnected,
    connectionState,
    dataFreshness,
    lastUpdateAt,
    lastMessageAt,
    liveAlerts,
    refresh,
  };
}

/** Lightweight ticker flash without remounting the whole tree. */
export function useTerminalClock(intervalMs = 1_000) {
  const [now, setNow] = useState(() => new Date());
  const ref = useRef<ReturnType<typeof setInterval> | null>(null);
  useEffect(() => {
    ref.current = setInterval(() => setNow(new Date()), intervalMs);
    return () => {
      if (ref.current) clearInterval(ref.current);
    };
  }, [intervalMs]);
  return now;
}

/** Fetch OHLCV chart for the user-selected symbol (watchlist / tape focus). */
export function useTerminalChart(
  symbol: string | null | undefined,
  fallback: TerminalChartSeries | null | undefined,
) {
  const effective = symbol?.trim() || fallback?.symbol || DEFAULT_ACTIVE_TICKER;
  const canReuseFallback =
    !!fallback?.symbol &&
    fallback.symbol.replace(/[-/]/g, "").toUpperCase() ===
      effective.replace(/[-/]/g, "").toUpperCase() &&
    (fallback.points?.length ?? 0) > 0;
  const tabVisible = useDocumentVisibility();

  return useQuery({
    queryKey: ["terminal", "chart", effective],
    queryFn: () => terminalApi.fetchChart(effective),
    enabled: Boolean(effective),
    staleTime: 60_000,
    refetchInterval: tabVisible ? 60_000 : false,
    placeholderData: canReuseFallback ? fallback : undefined,
  });
}
