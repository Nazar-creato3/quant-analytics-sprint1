/**
 * Browser client for QuantAnalytics Fincept Companion (127.0.0.1:17890).
 * Prefer companion over remote VPS API for launch / AppData on Windows.
 */

export const FINCEPT_COMPANION_PORT = 17890;
export const FINCEPT_COMPANION_BASE = `http://127.0.0.1:${FINCEPT_COMPANION_PORT}`;

export type FinceptCompanionStatus = {
  name?: string;
  ok?: boolean;
  installed?: boolean;
  runnable?: boolean;
  mode?: string;
  error?: string | null;
  docs?: string | null;
  companion?: boolean;
  detail?: Record<string, unknown>;
};

async function companionFetch<T>(
  path: string,
  init?: RequestInit,
  timeoutMs = 2500,
): Promise<T> {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    const res = await fetch(`${FINCEPT_COMPANION_BASE}${path}`, {
      ...init,
      signal: ctrl.signal,
      headers: {
        "Content-Type": "application/json",
        ...(init?.headers ?? {}),
      },
    });
    if (!res.ok) {
      const text = await res.text().catch(() => "");
      throw new Error(`companion_http_${res.status}${text ? `: ${text.slice(0, 200)}` : ""}`);
    }
    return (await res.json()) as T;
  } finally {
    clearTimeout(timer);
  }
}

/** Probe companion; returns null when not running / blocked. */
export async function probeFinceptCompanion(): Promise<FinceptCompanionStatus | null> {
  try {
    return await companionFetch<FinceptCompanionStatus>("/status", { method: "GET" }, 1800);
  } catch {
    return null;
  }
}

export async function companionLaunch(): Promise<Record<string, unknown>> {
  return companionFetch("/launch", { method: "POST", body: "{}" }, 15_000);
}

export async function companionSnapshot(): Promise<Record<string, unknown>> {
  return companionFetch("/snapshot", { method: "GET" }, 8_000);
}

export async function companionPushWatchlist(
  symbols: string[],
): Promise<Record<string, unknown>> {
  return companionFetch(
    "/push_watchlist",
    { method: "POST", body: JSON.stringify({ symbols }) },
    10_000,
  );
}
