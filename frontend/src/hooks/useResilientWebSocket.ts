"use client";

import { useCallback, useEffect, useRef, useState } from "react";

/** No *data* message for this long → force reconnect (heartbeats don't count). */
const STALE_DATA_SEC = 45;
/** No message at all (incl. heartbeat) for this long → force reconnect. */
const STALE_CONNECTION_SEC = 90;
/** Client-initiated ping when the socket is quiet. */
const CLIENT_PING_SEC = 20;
const INITIAL_RETRY_MS = 2_000;
const MAX_RETRY_MS = 30_000;

export type LiveConnectionState = "connecting" | "live" | "stale" | "disconnected";

export interface ResilientWsOptions {
  /** Build full ws URL (including token query params). Return null to skip connect. */
  buildUrl: () => string | null;
  enabled?: boolean;
  /** Called for every parsed message. Return true if message carries live data (not heartbeat). */
  isDataMessage?: (msg: Record<string, unknown>) => boolean;
  onMessage: (msg: Record<string, unknown>) => void;
  /** Label for console logging. */
  label?: string;
}

export interface ResilientWsResult {
  connectionState: LiveConnectionState;
  lastDataAt: number | null;
  lastMessageAt: number | null;
  reconnectCount: number;
}

function liveLog(label: string, event: string, detail?: unknown) {
  const ts = new Date().toISOString();
  // Always log in prod — silent frozen UI was the main operator complaint.
  // eslint-disable-next-line no-console
  console.info(`[live-ws:${label}] ${ts} ${event}`, detail ?? "");
}

function isHeartbeatType(type: string): boolean {
  return type === "connected" || type === "heartbeat" || type === "pong" || type === "subscribed";
}

/**
 * WebSocket hook with exponential-backoff reconnect and zombie detection.
 * Zombie fix: heartbeats keep the TCP socket "alive" but data can stop — we
 * track data freshness separately and reconnect when ticks/metrics go silent.
 */
export function useResilientWebSocket({
  buildUrl,
  enabled = true,
  isDataMessage,
  onMessage,
  label = "default",
}: ResilientWsOptions): ResilientWsResult {
  const onMessageRef = useRef(onMessage);
  onMessageRef.current = onMessage;
  const isDataRef = useRef(isDataMessage);
  isDataRef.current = isDataMessage;

  const [connectionState, setConnectionState] = useState<LiveConnectionState>("disconnected");
  const [lastDataAt, setLastDataAt] = useState<number | null>(null);
  const [lastMessageAt, setLastMessageAt] = useState<number | null>(null);
  const [reconnectCount, setReconnectCount] = useState(0);

  const lastMsgRef = useRef<number | null>(null);
  const lastDataRef = useRef<number | null>(null);

  useEffect(() => {
    if (typeof window === "undefined" || !enabled) {
      setConnectionState("disconnected");
      return;
    }

    let closed = false;
    let ws: WebSocket | null = null;
    let retryTimer: ReturnType<typeof setTimeout> | null = null;
    let staleTimer: ReturnType<typeof setInterval> | null = null;
    let attempt = 0;

    const scheduleReconnect = (reason: string) => {
      if (closed) return;
      attempt += 1;
      const delay = Math.min(INITIAL_RETRY_MS * 2 ** (attempt - 1), MAX_RETRY_MS);
      liveLog(label, "reconnect_scheduled", { attempt, delayMs: delay, reason });
      setReconnectCount(attempt);
      setConnectionState("disconnected");
      retryTimer = setTimeout(open, delay);
    };

    const forceReconnect = (reason: string) => {
      liveLog(label, "force_reconnect", { reason });
      ws?.close();
      scheduleReconnect(reason);
    };

    const open = () => {
      if (closed) return;
      const url = buildUrl();
      if (!url) {
        setConnectionState("disconnected");
        liveLog(label, "connect_skipped", "no url (missing token?)");
        return;
      }

      setConnectionState("connecting");
      liveLog(label, "connecting", url.replace(/token=[^&]+/, "token=***"));

      try {
        ws = new WebSocket(url);
      } catch (err) {
        liveLog(label, "connect_error", err);
        scheduleReconnect("connect_error");
        return;
      }

      ws.onopen = () => {
        attempt = 0;
        setReconnectCount(0);
        setConnectionState("live");
        liveLog(label, "connected");
      };

      ws.onclose = (ev) => {
        liveLog(label, "closed", { code: ev.code, reason: ev.reason });
        if (!closed) scheduleReconnect("closed");
      };

      ws.onerror = () => {
        liveLog(label, "error");
        ws?.close();
      };

      ws.onmessage = (ev) => {
        const now = Date.now();
        lastMsgRef.current = now;
        setLastMessageAt(now);

        try {
          const msg = JSON.parse(ev.data) as Record<string, unknown>;
          const type = String(msg.type ?? "");

          if (type === "ping") {
            ws?.send(JSON.stringify({ action: "pong" }));
            return;
          }

          const tracksData = isDataRef.current != null;
          const isData =
            !isHeartbeatType(type) && (isDataRef.current?.(msg) ?? !tracksData);

          if (isData) {
            lastDataRef.current = now;
            setLastDataAt(now);
            liveLog(label, "data_ok", { type });
          }

          setConnectionState("live");
          onMessageRef.current(msg);
        } catch (err) {
          liveLog(label, "parse_error", err);
        }
      };
    };

    open();

    staleTimer = setInterval(() => {
      if (closed || !ws || ws.readyState !== WebSocket.OPEN) return;
      const now = Date.now();

      const lastData = lastDataRef.current;
      const tracksData = isDataRef.current != null;
      if (tracksData && lastData && now - lastData > STALE_DATA_SEC * 1000) {
        setConnectionState("stale");
        forceReconnect("stale_data");
        return;
      }
      if (tracksData && lastData == null && lastMsgRef.current && now - lastMsgRef.current > STALE_DATA_SEC * 1000) {
        setConnectionState("stale");
        forceReconnect("no_data_yet");
        return;
      }

      const lastMsg = lastMsgRef.current;
      if (lastMsg && now - lastMsg > STALE_CONNECTION_SEC * 1000) {
        setConnectionState("stale");
        forceReconnect("stale_connection");
        return;
      }

      if (lastMsg && now - lastMsg > CLIENT_PING_SEC * 1000) {
        try {
          ws.send(JSON.stringify({ action: "ping" }));
          liveLog(label, "client_ping");
        } catch {
          forceReconnect("ping_failed");
        }
      }
    }, 5_000);

    return () => {
      closed = true;
      if (retryTimer) clearTimeout(retryTimer);
      if (staleTimer) clearInterval(staleTimer);
      ws?.close();
      setConnectionState("disconnected");
    };
  }, [buildUrl, enabled, label]);

  return { connectionState, lastDataAt, lastMessageAt, reconnectCount };
}
