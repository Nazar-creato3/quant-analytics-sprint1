"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { PortfolioMetrics, PositionsSnapshot } from "@/types";
import { useResilientWebSocket } from "@/hooks/useResilientWebSocket";

function wsBaseUrl(): string {
  if (typeof window === "undefined") return "";
  const configured = process.env.NEXT_PUBLIC_API_URL?.trim();
  const origin =
    configured ||
    (window.location.hostname === "localhost" ? "http://localhost:8000" : window.location.origin);
  return origin.replace(/^http/, "ws").replace(/\/$/, "");
}

export function useCockpitWebSocket(
  symbol: string,
  onPrice: (data: Record<string, unknown>) => void,
) {
  const onPriceRef = useRef(onPrice);
  onPriceRef.current = onPrice;

  const buildUrl = useCallback(() => {
    if (!symbol) return null;
    const token = localStorage.getItem("access_token");
    if (!token) return null;
    return `${wsBaseUrl()}/api/v1/ws/cockpit?token=${encodeURIComponent(token)}&symbol=${encodeURIComponent(symbol)}`;
  }, [symbol]);

  const handleMessage = useCallback((msg: Record<string, unknown>) => {
    if (msg.type === "price" && msg.data) {
      onPriceRef.current(msg.data as Record<string, unknown>);
    }
  }, []);

  const { connectionState } = useResilientWebSocket({
    buildUrl,
    enabled: Boolean(symbol),
    label: "cockpit",
    isDataMessage: (msg) => msg.type === "price",
    onMessage: handleMessage,
  });

  return { connected: connectionState === "live" || connectionState === "stale" };
}

/** NavBar TRD/BLNC/SUM — same payload as GET /portfolio/metrics, ~5s cadence. */
export function usePortfolioMetricsWebSocket(
  enabled: boolean,
  onMetrics: (metrics: PortfolioMetrics) => void,
  userKey?: string,
) {
  const onMetricsRef = useRef(onMetrics);
  onMetricsRef.current = onMetrics;

  const buildUrl = useCallback(() => {
    const token = localStorage.getItem("access_token");
    if (!token) return null;
    return `${wsBaseUrl()}/api/v1/ws/portfolio?token=${encodeURIComponent(token)}`;
  }, [userKey]);

  const handleMessage = useCallback((msg: Record<string, unknown>) => {
    if (msg.type === "portfolio_metrics" && msg.data) {
      onMetricsRef.current(msg.data as PortfolioMetrics);
      // Positions have a dedicated WS channel; invalidating the whole live-query
      // graph every ~5s caused redundant REST storms and UI freezes.
    }
  }, []);

  useResilientWebSocket({
    buildUrl,
    enabled,
    label: "portfolio",
    isDataMessage: (msg) => msg.type === "portfolio_metrics",
    onMessage: handleMessage,
  });
}

/** Open positions snapshot — same enrichment as GET /maneuvers, ~5s cadence. */
export function useLivePositionsWebSocket(
  enabled: boolean,
  onSnapshot: (snapshot: PositionsSnapshot) => void,
  userKey?: string,
): { connectionState: ReturnType<typeof useResilientWebSocket>["connectionState"] } {
  const onSnapshotRef = useRef(onSnapshot);
  onSnapshotRef.current = onSnapshot;

  const buildUrl = useCallback(() => {
    const token = localStorage.getItem("access_token");
    if (!token) return null;
    return `${wsBaseUrl()}/api/v1/ws/positions?token=${encodeURIComponent(token)}`;
  }, [userKey]);

  const handleMessage = useCallback((msg: Record<string, unknown>) => {
    if (msg.type === "positions_snapshot" && msg.data) {
      onSnapshotRef.current(msg.data as PositionsSnapshot);
    }
  }, []);

  const { connectionState } = useResilientWebSocket({
    buildUrl,
    enabled,
    label: "positions",
    isDataMessage: (msg) => msg.type === "positions_snapshot",
    onMessage: handleMessage,
  });

  return { connectionState };
}

export function useChatWebSocket(
  conversationId: string | null,
  onMessage: (payload: Record<string, unknown>) => void,
) {
  const onMessageRef = useRef(onMessage);
  onMessageRef.current = onMessage;

  const buildUrl = useCallback(() => {
    if (!conversationId) return null;
    const token = localStorage.getItem("access_token");
    if (!token) return null;
    return `${wsBaseUrl()}/api/v1/ws/chat/${encodeURIComponent(conversationId)}?token=${encodeURIComponent(token)}`;
  }, [conversationId]);

  const handleMessage = useCallback((msg: Record<string, unknown>) => {
    if (msg.type === "chat_message") {
      onMessageRef.current(msg);
    }
  }, []);

  useResilientWebSocket({
    buildUrl,
    enabled: Boolean(conversationId),
    label: "chat",
    isDataMessage: (msg) => msg.type === "chat_message",
    onMessage: handleMessage,
  });
}
