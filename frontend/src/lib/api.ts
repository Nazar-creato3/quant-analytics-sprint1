// Quant Analytics API client
// Handles auth headers, token refresh, and typed responses.

import axios, { AxiosInstance, AxiosRequestConfig, InternalAxiosRequestConfig } from "axios";
import { syncAuthFromCookie } from "@/lib/auth-sync";
import { resetDashboardMode } from "@/lib/dashboard-mode";
import { notifyAuthSessionChanged } from "@/lib/user-scoped-query";
import type { PortfolioReturns, SimpleAltResponse } from "@/lib/returns";

export type { SimpleAltResponse };
import type { UnifiedRiskSnapshot } from "@/lib/risk-engine";
import type {
  AssetCockpitData,
  DirectDealsSymbol,
  DealIntent,
  ForecastData,
  MarketForecastData,
  ComposerConfig,
  ComposerSchema,
  ComposerValidationResult,
  CompiledStrategyConfig,
  AuditLog, BacktestResult, CloseAllPositionsResult, HealthStatus, Maneuver,
  ManeuverReport, MarketAnalysisResult, LlmStatus, NewsArticle, OHLCVBar, PaginatedResponse,
  PilotStatus, PortfolioMetrics, PortfolioRefreshResult, RefreshVenueBalancesResult, RiskStatus, StopDrillResult,
  PortfolioRiskAnalytics, ComposerBacktestResult,
  PipelineRunResponse, TokenResponse, User, UserSettings, VenueBalancesResponse,
  AccountSummary, PaperTransferResult, ManualOrder, OrderBookSnapshot, OrderTicketPrefill, RecentTrade,
  SymbolTradingRules,
  SlippageEstimate, LivePerformanceMetrics, ModelDriftSnapshot, ManualOrderSide, ManualOrderType,
  PositionAuditStatus, PositionAuditTriggerResult, PositionAuditSummary, TickerBook,
  RobotLotBook, RobotPlan, RobotLevel,
} from "@/types";

function setAuthCookie(token: string, maxAgeSeconds: number) {
  if (typeof document === "undefined") return;
  const secure =
    typeof window !== "undefined" && window.location.protocol === "https:"
      ? "; Secure"
      : "";
  document.cookie = `access_token=${encodeURIComponent(token)}; path=/; max-age=${maxAgeSeconds}; SameSite=Lax${secure}`;
}

function clearAuthCookie() {
  if (typeof document === "undefined") return;
  document.cookie = "access_token=; path=/; max-age=0; SameSite=Lax";
}

function isAuthEndpoint(url: string | undefined): boolean {
  if (!url) return false;
  return (
    url.includes("/auth/login") ||
    url.includes("/auth/register") ||
    url.includes("/auth/refresh") ||
    url.includes("/auth/recover") ||
    url.includes("/auth/reset") ||
    url.includes("/auth/wasnt-me") ||
    url.includes("/auth/verify-email/") ||
    url.includes("/admissions/apply") ||
    url.includes("/applications/")
  );
}

const API_PREFIX = "/api/v1";

/**
 * Resolve the API origin for axios.
 *
 * Production (nginx/Caddy) proxies /api/* on the same host as the UI, so the
 * browser should use a relative origin (empty string). NEXT_PUBLIC_API_URL is
 * inlined at Docker build time; when omitted, older images incorrectly fell back
 * to http://localhost:8000 and login failed with "Network Error".
 */
function resolveApiUrl(): string {
  if (typeof window !== "undefined") {
    const host = window.location.hostname;
    const port = window.location.port;
    // Lane3 3120 and ci-e2e 3150 proxy /api/* same-origin (next.config rewrite).
    if (
      host === "frontend" ||
      port === "3000" ||
      port === "3100" ||
      ((host === "localhost" || host === "127.0.0.1") && (port === "3120" || port === "3150" || port === "3200"))
    ) {
      return "";
    }
  }
  const configured = process.env.NEXT_PUBLIC_API_URL?.trim();
  if (configured) {
    return configured.replace(/\/$/, "");
  }
  if (typeof window !== "undefined") {
    const host = window.location.hostname;
    const port = window.location.port;
    if (host === "localhost" || host === "127.0.0.1") {
      // Pin IPv4 loopback. `localhost` can resolve to ::1, where another
      // listener may own port 8000 while this API is bound to 127.0.0.1.
      return "http://127.0.0.1:8000";
    }
    // Production: nginx/Caddy proxy /api/* on the same public host.
    return "";
  }
  return (
    process.env.INTERNAL_API_URL?.trim().replace(/\/$/, "") ||
    "http://backend:8000"
  );
}

const API_URL = resolveApiUrl();

const CSRF_COOKIE_NAME = "apex_csrf";
const CSRF_HEADER_NAME = "X-CSRF-Token";
const UNSAFE_HTTP_METHODS = new Set(["post", "put", "patch", "delete"]);

function readCsrfCookie(): string | null {
  if (typeof document === "undefined") return null;
  const escaped = CSRF_COOKIE_NAME.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const match = document.cookie.match(new RegExp(`(?:^|; )${escaped}=([^;]*)`));
  return match ? decodeURIComponent(match[1]) : null;
}

let csrfBootstrap: Promise<void> | null = null;

async function ensureCsrfCookie(): Promise<string | null> {
  const existing = readCsrfCookie();
  if (existing) return existing;
  if (!csrfBootstrap) {
    csrfBootstrap = axios
      .get(`${API_URL}${API_PREFIX}/auth/csrf-token`, { withCredentials: true })
      .then(() => undefined)

      .catch(() => undefined) // CSRF may be off in local/dev (404) — login must still succeed.
      .finally(() => {
        csrfBootstrap = null;
      });
  }
  await csrfBootstrap;
  return readCsrfCookie();
}

/** Warm CSRF + auth cookie sync — call on app boot for mobile/hard-refresh sessions. */
export async function bootstrapAuthSession(): Promise<void> {
  if (typeof window === "undefined") return;
  syncAuthFromCookie();
  const token =
    localStorage.getItem("access_token") || readCookie("access_token");
  if (token) {
    await ensureCsrfCookie();
  }
}

function readCookie(name: string): string | null {
  if (typeof document === "undefined") return null;
  const escaped = name.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const match = document.cookie.match(new RegExp(`(?:^|; )${escaped}=([^;]*)`));
  return match ? decodeURIComponent(match[1]) : null;
}

type ApiRequestConfig = InternalAxiosRequestConfig & {
  _retry?: boolean;
  _csrfRetry?: boolean;
  /** Do not hard-redirect to /login on auth failure (graceful UI fallback). */
  skipAuthRedirect?: boolean;
};

let authRedirectPending = false;

// ── Axios instance ────────────────────────────────────────────────────────────

const api: AxiosInstance = axios.create({
  baseURL: `${API_URL}${API_PREFIX}`,
  headers: { "Content-Type": "application/json" },
  timeout: 30_000,
  withCredentials: true,
});

// Attach Bearer token from localStorage (sync cookie first on hard refresh)
api.interceptors.request.use(async (config) => {
  if (typeof window !== "undefined") {
    syncAuthFromCookie();
    const token = localStorage.getItem("access_token");
    if (token) {
      config.headers.Authorization = `Bearer ${token}`;
    }
    const method = (config.method ?? "get").toLowerCase();
    if (
      UNSAFE_HTTP_METHODS.has(method) &&
      config.headers.Authorization &&
      !isAuthEndpoint(config.url)
    ) {
      const csrf = (await ensureCsrfCookie()) ?? readCsrfCookie();
      if (csrf) {
        config.headers[CSRF_HEADER_NAME] = csrf;
      }
    }
  }
  return config;
});

/** Header mode (Учебный / Боевой), persisted by ProductContext. */
export function currentBookMode(): "paper" | "live" {
  if (typeof window === "undefined") return "paper";
  try {
    return window.localStorage.getItem("qa.bookMode") === "live" ? "live" : "paper";
  } catch {
    return "paper";
  }
}

export class LiveOrderCancelled extends Error {
  constructor() {
    super("Заявка не отправлена");
  }
}

/** A real-account order needs an explicit yes every time. */
export function confirmLiveOrNot(mode: "paper" | "live"): void {
  if (mode !== "live" || typeof window === "undefined") return;
  const ok = window.confirm("Боевой режим: брокеру будет отправлена реальная заявка с вашего счёта. Отправить?");
  if (!ok) throw new LiveOrderCancelled();
}

// Auto-refresh on 401; retry once on CSRF mismatch (common on fresh mobile sessions).
api.interceptors.response.use(
  (response) => response,
  async (error) => {
    const original = error.config as ApiRequestConfig | undefined;
    const csrfDetail = error.response?.data?.detail;
    if (
      error.response?.status === 403 &&
      original &&
      !original._csrfRetry &&
      typeof csrfDetail === "string" &&
      csrfDetail.toLowerCase().includes("csrf")
    ) {
      original._csrfRetry = true;
      const csrf = await ensureCsrfCookie();
      if (csrf) {
        original.headers[CSRF_HEADER_NAME] = csrf;
        return api(original);
      }
    }
    if (
      error.response?.status === 403 &&
      error.response?.data?.detail === "phone_confirmation_required" &&
      typeof window !== "undefined" &&
      !window.location.pathname.startsWith("/verify-phone")
    ) {
      const next = encodeURIComponent(window.location.pathname + window.location.search);
      window.location.href = `/verify-phone?next=${next}`;
      return Promise.reject(error);
    }
    if (
      error.response?.status === 401 &&
      original &&
      !original._retry &&
      !isAuthEndpoint(original.url)
    ) {
      original._retry = true;
      try {
        const refreshToken = localStorage.getItem("refresh_token");
        if (!refreshToken) throw new Error("No refresh token");
        const { data } = await axios.post<TokenResponse>(
          `${API_URL}${API_PREFIX}/auth/refresh`,
          { refresh_token: refreshToken }
        );
        localStorage.setItem("access_token", data.access_token);
        localStorage.setItem("refresh_token", data.refresh_token);
        setAuthCookie(data.access_token, data.expires_in);
        original.headers.Authorization = `Bearer ${data.access_token}`;
        return api(original);
      } catch {
        localStorage.removeItem("access_token");
        localStorage.removeItem("refresh_token");
        clearAuthCookie();
        if (!original.skipAuthRedirect && !authRedirectPending) {
          authRedirectPending = true;
          window.location.href = "/login";
        }
      }
    }
    return Promise.reject(error);
  }
);

// ── Auth ──────────────────────────────────────────────────────────────────────

function isAuthenticatedTokenResponse(data: TokenResponse): boolean {
  return Boolean(
    data.access_token &&
      !data.must_change_password &&
      !data.webauthn_required &&
      !data.webauthn_registration_required &&
      !data.two_factor_required,
  );
}

/** Store tokens + CSRF cookie after a fully authenticated login. */
export async function finalizeAuthenticatedSession(data: TokenResponse): Promise<void> {
  authApi.persistSession(data);
  notifyAuthSessionChanged();
  await ensureCsrfCookie();
}

export const authApi = {
  persistSession: (data: TokenResponse) => {
    localStorage.setItem("access_token", data.access_token);
    localStorage.setItem("refresh_token", data.refresh_token);
    setAuthCookie(data.access_token, data.expires_in);
    resetDashboardMode();
  },

  /** POST /auth/login without storing tokens — use login-flow for multi-step auth. */
  loginRaw: async (
    email: string,
    password: string,
    extras?: {
      fingerprint?: string;
      user_agent?: string;
      webauthn_credential?: Record<string, unknown>;
    },
  ): Promise<TokenResponse> => {
    const { data } = await api.post<TokenResponse>(
      "/auth/login",
      {
        email,
        password,
        fingerprint: extras?.fingerprint,
        user_agent: extras?.user_agent,
        webauthn_credential: extras?.webauthn_credential,
      },
      { timeout: 90_000 },
    );
    return data;
  },

  login: async (
    email: string,
    password: string,
    extras?: { fingerprint?: string; user_agent?: string },
  ): Promise<TokenResponse> => {
    const data = await authApi.loginRaw(email, password, extras);
    if (!isAuthenticatedTokenResponse(data)) {
      throw new Error("Login requires additional steps");
    }
    authApi.persistSession(data);
    await ensureCsrfCookie();
    return data;
  },

  changePassword: async (
    email: string,
    currentPassword: string,
    newPassword: string,
  ): Promise<{ ok: boolean; webauthn_registration_required: boolean }> => {
    const { data } = await api.post("/auth/change-password", {
      email,
      current_password: currentPassword,
      new_password: newPassword,
    });
    return data;
  },

  requestPasswordChange: async (
    newPassword: string,
    confirmPassword: string,
  ): Promise<{ ok: boolean; message: string; dev_code?: string }> => {
    const { data } = await api.post("/auth/password-change/request", {
      new_password: newPassword,
      confirm_password: confirmPassword,
    });
    return data;
  },

  confirmPasswordChange: async (body: {
    newPassword: string;
    confirmPassword: string;
    code?: string;
    token?: string;
  }): Promise<{ ok: boolean; message: string }> => {
    const { data } = await api.post("/auth/password-change/confirm", {
      new_password: body.newPassword,
      confirm_password: body.confirmPassword,
      code: body.code,
      token: body.token,
    });
    return data;
  },

  requestPasswordRecovery: async (email: string): Promise<{ ok: boolean; message: string }> => {
    const { data } = await api.post("/auth/recover", { email });
    return data;
  },

  resetPassword: async (body: {
    token: string;
    newPassword: string;
    confirmPassword: string;
  }): Promise<{ ok: boolean; message: string }> => {
    const { data } = await api.post("/auth/reset", {
      token: body.token,
      new_password: body.newPassword,
      confirm_password: body.confirmPassword,
    });
    return data;
  },

  reportUnauthorizedPasswordChange: async (
    token: string,
  ): Promise<{ ok: boolean; message: string }> => {
    const { data } = await api.post("/auth/wasnt-me", { token });
    return data;
  },

  requestEmailVerification: async (email: string): Promise<{ ok: boolean; message: string }> => {
    const { data } = await api.post("/auth/verify-email/request", { email });
    return data;
  },

  confirmEmailVerification: async (token: string): Promise<{ ok: boolean; message: string }> => {
    const { data } = await api.post("/auth/verify-email/confirm", { token });
    return data;
  },

  webauthnRegisterOptions: async (
    email: string,
    password: string,
  ): Promise<Record<string, unknown>> => {
    const { data } = await api.post("/auth/webauthn/register/options", {
      email,
      password,
    });
    return data;
  },

  webauthnRegisterVerify: async (
    email: string,
    password: string,
    credential: Record<string, unknown>,
  ): Promise<void> => {
    await api.post("/auth/webauthn/register/verify", {
      email,
      password,
      credential,
    });
  },

  webauthnLoginOptions: async (email: string): Promise<Record<string, unknown>> => {
    const { data } = await api.post("/auth/webauthn/login/options", { email });
    return data;
  },

  logout: () => {
    localStorage.removeItem("access_token");
    localStorage.removeItem("refresh_token");
    clearAuthCookie();
  },

  me: async (): Promise<User> => {
    const { data } = await api.get<User>("/auth/me", {
      skipAuthRedirect: true,
    } as ApiRequestConfig);
    return data;
  },

  register: async (payload: {
    email: string;
    password: string;
    fingerprint?: string;
    user_agent?: string;
    timezone_mismatch?: boolean;
    contact_name?: string;
    contact_phone?: string;
    jurisdiction?: string;
    capital_range?: string;
    experience_level?: string;
    strategy_interest?: string;
    notes?: string;
    accept_terms: boolean;
    consent_pd: boolean;
    phone?: string;
    phone_code?: string;
  }): Promise<TokenResponse> => {
    const { data } = await api.post<TokenResponse>("/auth/register", payload, {
      skipAuthRedirect: true,
    } as ApiRequestConfig);
    if (!data.access_token) {
      return data;
    }
    localStorage.setItem("access_token", data.access_token);
    localStorage.setItem("refresh_token", data.refresh_token);
    setAuthCookie(data.access_token, data.expires_in);
    await ensureCsrfCookie();
    resetDashboardMode();
    return data;
  },

  sendPhoneCode: async (phone: string): Promise<{ sent: boolean; phone: string; ttl_sec: number; dev_code?: string }> => {
    const { data } = await api.post("/auth/phone/send-code", { phone }, { skipAuthRedirect: true } as ApiRequestConfig);
    return data;
  },

  confirmPhone: async (phone: string, code: string): Promise<void> => {
    const { data } = await api.post<TokenResponse>("/auth/phone/confirm", { phone, code });
    if (data.access_token) {
      localStorage.setItem("access_token", data.access_token);
      setAuthCookie(data.access_token, data.expires_in);
      notifyAuthSessionChanged();
    }
  },

  verifyTwoFactor: async (payload: {
    pending_token: string;
    code?: string;
    backup_code?: string;
  }): Promise<TokenResponse> => {
    const { data } = await api.post<TokenResponse>("/auth/login/verify-2fa", payload, {
      skipAuthRedirect: true,
    } as ApiRequestConfig);
    return data;
  },
};

export const twoFactorApi = {
  status: async (): Promise<{
    enabled: boolean;
    enabled_at: string | null;
    backup_codes_remaining: number | null;
    required_for_admin: boolean;
  }> => {
    const { data } = await api.get("/two-factor/status");
    return data;
  },
  enableInitiate: async (): Promise<{
    secret: string;
    provisioning_uri: string;
    qr_code_base64: string;
    manual_hint: string;
  }> => {
    const { data } = await api.post("/two-factor/enable/initiate");
    return data;
  },
  enableConfirm: async (code: string): Promise<{ success: boolean; backup_codes: string[]; message: string }> => {
    const { data } = await api.post("/two-factor/enable/confirm", { code });
    return data;
  },
  disable: async (code: string, password: string): Promise<{ success: boolean; message: string }> => {
    const { data } = await api.post("/two-factor/disable", { code, password });
    return data;
  },
  regenerateBackupCodes: async (
    code: string,
  ): Promise<{ success: boolean; backup_codes: string[]; message: string }> => {
    const { data } = await api.post("/two-factor/regenerate-backup-codes", { code });
    return data;
  },
  reauth: async (code: string): Promise<{ success: boolean; reauth_token: string; expires_in: number }> => {
    const { data } = await api.post("/two-factor/reauth", { code });
    return data;
  },
};

// ── Pipeline ──────────────────────────────────────────────────────────────────

export const pipelineApi = {
  run: async (watchlist?: string[], portfolioSize?: number): Promise<PipelineRunResponse> => {
    const { data } = await api.post<PipelineRunResponse>("/pipeline/run", {
      watchlist,
      portfolio_size: portfolioSize,
    });
    return data;
  },

  pollStatus: async (runId: string): Promise<PipelineRunResponse> => {
    const { data } = await api.get<PipelineRunResponse>(
      `/pipeline/status/${encodeURIComponent(runId.trim())}`,
      {
      timeout: 25_000,
      },
    );
    return data;
  },

  listReports: async (page = 1, pageSize = 20): Promise<PaginatedResponse<ManeuverReport>> => {
    const { data } = await api.get<PaginatedResponse<ManeuverReport>>("/pipeline/reports", {
      params: { page, page_size: pageSize },
    });
    return data;
  },

  getReport: async (reportId: string): Promise<ManeuverReport> => {
    const { data } = await api.get<ManeuverReport>(`/pipeline/reports/${reportId}`);
    return data;
  },

  getReportText: async (reportId: string): Promise<string> => {
    const { data } = await api.get<{ text: string }>(`/pipeline/reports/${reportId}/text`);
    return data.text;
  },
};

// ── Maneuvers ─────────────────────────────────────────────────────────────────

export const maneuversApi = {
  list: async (params?: {
    ticker?: string;
    status?: string;
    page?: number;
    page_size?: number;
    skip_confidence_filter?: boolean;
  }): Promise<PaginatedResponse<Maneuver>> => {
    const { data } = await api.get<PaginatedResponse<Maneuver>>("/maneuvers", { params });
    return data;
  },

  get: async (id: string): Promise<Maneuver> => {
    const { data } = await api.get<Maneuver>(`/maneuvers/${id}`);
    return data;
  },

  book: async (ticker: string): Promise<TickerBook> => {
    const { data } = await api.get<TickerBook>(`/maneuvers/book/${encodeURIComponent(ticker)}`);
    return data;
  },

  approve: async (
    id: string,
    note?: string,
    options?: { time_horizon?: string; expiry_at?: string },
  ): Promise<Maneuver> => {
    const trading_mode = currentBookMode();
    confirmLiveOrNot(trading_mode);
    const { data } = await api.post<Maneuver>(`/maneuvers/${id}/approve`, {
      maneuver_id: id,
      action: "approve",
      note,
      time_horizon: options?.time_horizon,
      expiry_at: options?.expiry_at,
      trading_mode,
    });
    return data;
  },

  reject: async (id: string, note?: string): Promise<Maneuver> => {
    const { data } = await api.post<Maneuver>(`/maneuvers/${id}/approve`, {
      maneuver_id: id,
      action: "reject",
      note,
    });
    return data;
  },

  edit: async (
    id: string,
    body: {
      size_usd?: number;
      entry_price?: number;
      stop_loss?: number;
      take_profit?: number;
      time_horizon?: string;
      expiry_at?: string;
      note?: string;
    },
  ): Promise<Maneuver> => {
    const { data } = await api.patch<Maneuver>(`/maneuvers/${id}`, body);
    return data;
  },

  cancel: async (
    id: string,
    options?: { note?: string; reason?: string },
  ): Promise<{
    maneuver_id: string;
    ticker: string;
    status_before: string;
    status_after: string;
    action: string;
    size_usd: number;
    realized_pnl?: number | null;
    message: string;
  }> => {
    const { data } = await api.post(`/maneuvers/${id}/cancel`, options ?? {});
    return data;
  },
};

export const robotApi = {
  book: async (ticker: string): Promise<RobotLotBook> => {
    const { data } = await api.get<RobotLotBook>(`/robot/book/${encodeURIComponent(ticker)}`);
    return data;
  },

  plans: async (ticker?: string): Promise<RobotPlan[]> => {
    const { data } = await api.get<RobotPlan[]>("/robot/plans", {
      params: ticker ? { ticker } : undefined,
    });
    return data;
  },

  fromFreqtrade: async (body: {
    ticker: string;
    entry: number;
    side?: string;
    mode?: string;
    minimal_roi?: Record<string, number>;
    stoploss?: number;
    trailing_stop?: boolean;
    trailing_stop_positive?: number;
    use_apex_defaults?: boolean;
    maneuver_id?: string;
  }): Promise<RobotPlan> => {
    const { data } = await api.post<RobotPlan>("/robot/plans/from-freqtrade", body);
    return data;
  },

  createTyped: async (body: {
    ticker: string;
    entry: number;
    side?: string;
    mode?: string;
    plan_type: "custom" | "grid" | "dca";
    plan_params?: Record<string, unknown>;
    maneuver_id?: string;
  }): Promise<RobotPlan> => {
    const { data } = await api.post<RobotPlan>("/robot/plans/typed", body);
    return data;
  },

  shadow: async (body: {
    levels?: Array<Record<string, unknown>>;
    bars: Array<{ high: number; low: number; close: number }>;
    side?: string;
    entry?: number;
    qty?: number;
    fee_rate?: number;
    kill_switch_pct?: number | null;
    use_apex_defaults?: boolean;
    slippage_pct?: number;
    latency_bars?: number;
    partial_fill_min?: number;
    seed?: number;
  }): Promise<Record<string, unknown>> => {
    const { data } = await api.post<Record<string, unknown>>("/robot/shadow", body);
    return data;
  },

  planLevels: async (planId: string) => {
    const { data } = await api.get<{
      plan_id: string;
      levels: RobotLevel[];
      fills: Array<Record<string, unknown>>;
      status: string;
    }>(`/robot/plans/${encodeURIComponent(planId)}/levels`);
    return data;
  },

  pauseLevel: async (planId: string, levelId: string) => {
    const { data } = await api.post(`/robot/plans/${encodeURIComponent(planId)}/levels/${encodeURIComponent(levelId)}/pause`);
    return data;
  },

  pausePlan: async (planId: string) => {
    const { data } = await api.post(`/robot/plans/${encodeURIComponent(planId)}/pause`);
    return data;
  },

  cancelPlan: async (planId: string) => {
    const { data } = await api.post(`/robot/plans/${encodeURIComponent(planId)}/cancel`);
    return data;
  },

  capabilities: async (planId: string) => {
    const { data } = await api.get<Record<string, unknown>>(
      `/robot/plans/${encodeURIComponent(planId)}/capabilities`
    );
    return data;
  },

  equityCurve: async (planId: string, mode = "live") => {
    const { data } = await api.get<{ curve: Array<Record<string, unknown>> }>(
      `/robot/plans/${encodeURIComponent(planId)}/equity-curve`,
      { params: { mode } }
    );
    return data;
  },

  requestFlatten: async (body: {
    reason?: string;
    plan_ids?: string[];
    required_approvals?: number;
  }) => {
    const { data } = await api.post<Record<string, unknown>>("/robot/governance/flatten", body);
    return data;
  },

  approveFlatten: async (logId: string) => {
    const { data } = await api.post<Record<string, unknown>>("/robot/governance/approve", {
      log_id: logId,
    });
    return data;
  },
};

export const ordersApi = {
  submit: async (body: {
    ticker: string;
    side: ManualOrderSide;
    order_type: ManualOrderType;
    quantity: number;
    limit_price?: number;
    stop_price?: number;
    time_in_force?: string;
    gtd_expires_at?: string;
    trailing_stop_pct?: number;
    oco_sibling_price?: number;
    bracket?: { stop_loss?: number; take_profit?: number };
    maneuver_id?: string;
    position_time_horizon?: string;
    position_expiry_at?: string;
    note?: string;
    risk_confirm?: boolean;
  }): Promise<ManualOrder> => {
    const trading_mode = currentBookMode();
    confirmLiveOrNot(trading_mode);
    const { data } = await api.post<ManualOrder>("/orders", { ...body, trading_mode });
    return data;
  },

  riskGatePreview: async (body: {
    user_id: string;
    ticker: string;
    qty: number;
    price: number;
    confirmed?: boolean;
  }) => {
    const { data } = await api.post<import("@/lib/risk-gate").RiskGateDecision>("/risk-gate/preview", {
      ...body,
      kind: "manual_order",
      actor: "human",
    });
    return data;
  },

  list: async (params?: { ticker?: string; status?: string }): Promise<ManualOrder[]> => {
    const { data } = await api.get<ManualOrder[]>("/orders", { params });
    return data;
  },

  cancel: async (orderId: string): Promise<ManualOrder> => {
    const { data } = await api.post<ManualOrder>(`/orders/${orderId}/cancel`);
    return data;
  },

  modify: async (
    orderId: string,
    body: { limit_price?: number; quantity?: number },
  ): Promise<ManualOrder> => {
    const { data } = await api.patch<ManualOrder>(`/orders/${orderId}`, body);
    return data;
  },

  prefillFromManeuver: async (maneuverId: string): Promise<OrderTicketPrefill> => {
    const { data } = await api.post<OrderTicketPrefill>("/orders/prefill/maneuver", {
      maneuver_id: maneuverId,
    });
    return data;
  },

  orderBook: async (ticker: string): Promise<OrderBookSnapshot> => {
    const { data } = await api.get<OrderBookSnapshot>(`/orders/book/${encodeURIComponent(ticker)}`);
    return data;
  },

  recentTrades: async (ticker: string, limit = 50): Promise<RecentTrade[]> => {
    const { data } = await api.get<RecentTrade[]>(
      `/orders/recent-trades/${encodeURIComponent(ticker)}`,
      { params: { limit } },
    );
    return data;
  },

  symbolRules: async (ticker: string): Promise<SymbolTradingRules> => {
    const { data } = await api.get<SymbolTradingRules>(
      `/orders/symbol-rules/${encodeURIComponent(ticker)}`,
    );
    return data;
  },

  slippage: async (ticker: string, notionalUsd: number): Promise<SlippageEstimate> => {
    const { data } = await api.get<SlippageEstimate>(
      `/orders/slippage/${encodeURIComponent(ticker)}`,
      { params: { notional_usd: notionalUsd } },
    );
    return data;
  },
};

export const signalMonitoringApi = {
  livePerformance: async (): Promise<LivePerformanceMetrics> => {
    const { data } = await api.get<LivePerformanceMetrics>("/signal-monitoring/live-performance");
    return data;
  },

  modelDrift: async (): Promise<ModelDriftSnapshot> => {
    const { data } = await api.get<ModelDriftSnapshot>("/signal-monitoring/model-drift");
    return data;
  },
};

// ── Market Data ───────────────────────────────────────────────────────────────

// ── Futures desk (MOEX FORTS) ────────────────────────────────────────────────

export interface FuturesContract {
  secid: string;
  shortname?: string | null;
  name?: string | null;
  asset: string;
  title?: string | null;
  group: "index" | "fx" | "commodity" | "stock" | "other";
  hedge?: string | null;
  price?: number | null;
  prev_settle?: number | null;
  change?: number | null;
  tick?: number | null;
  tick_value?: number | null;
  point_value?: number | null;
  contract_value?: number | null;
  initial_margin?: number | null;
  leverage?: number | null;
  expiry?: string | null;
  days_to_expiry?: number | null;
  perpetual?: boolean;
  lot?: number | null;
  open_interest?: number | null;
  volume?: number | null;
  fee?: number | null;
  next_secid?: string | null;
  next_price?: number | null;
}

export interface FuturesPosition {
  secid: string;
  title?: string | null;
  price?: number | null;
  point_value?: number | null;
  initial_margin?: number | null;
  expiry?: string | null;
  days_to_expiry?: number | null;
  perpetual?: boolean;
  next_secid?: string | null;
  qty: number;
  side: "long" | "short";
  notional: number;
  margin: number;
  variation_today?: number | null;
  pnl_since_entry?: number | null;
  entry_price?: number | null;
  roll_soon?: boolean;
}

export interface FuturesDesk {
  contracts: FuturesContract[];
  positions: FuturesPosition[];
  cash_rub?: number | null;
  hedge: {
    equity_value_rub?: number | null;
    beta?: number | null;
    index_vol?: number | null;
    portfolio_vol?: number | null;
    fx_exposure_rub?: Record<string, number>;
    skipped?: string[];
  };
  delayed?: boolean;
  freshness?: "realtime" | "delayed" | "closed";
  as_of?: string;
  source?: string;
  data_status?: string;
  reason?: string | null;
}

export const futuresApi = {
  desk: async (mode = "paper"): Promise<FuturesDesk> => {
    const { data } = await api.get<FuturesDesk>("/futures/desk", { params: { mode } });
    return data;
  },
  contracts: async (q: string): Promise<FuturesContract[]> => {
    const { data } = await api.get<{ items: FuturesContract[] }>("/futures/contracts", { params: { q } });
    return data.items || [];
  },
};

export const marketApi = {
  getBars: async (
    ticker: string,
    timeframe = "1d",
    limit = 100,
    options?: { forceRefresh?: boolean }
  ): Promise<OHLCVBar[]> => {
    const { data } = await api.get<OHLCVBar[]>(`/market/bars/${ticker}`, {
      params: {
        timeframe,
        limit,
        ...(options?.forceRefresh ? { force_refresh: true } : {}),
      },
    });
    return data;
  },

  getQuote: async (
    ticker: string,
    options?: { forceRefresh?: boolean; enrich?: boolean }
  ): Promise<Record<string, unknown>> => {
    const params: Record<string, boolean> = {};
    if (options?.forceRefresh) params.force_refresh = true;
    // Default: fast quote (price/change). Opt-in enrich for Info tabs only.
    if (options?.enrich) params.enrich = true;
    const { data } = await api.get(`/market/quote/${ticker}`, {
      params: Object.keys(params).length ? params : undefined,
    });
    return data;
  },

  computeIndicators: async (body: {
    ticker: string;
    timeframe: string;
    bars: OHLCVBar[];
  }): Promise<{ overlays: Record<string, (number | null)[]>; freshness_label: string }> => {
    const { data } = await api.post("/market/indicators", body);
    return data;
  },

  getNameCard: async (ticker: string, direction?: string): Promise<Record<string, unknown>> => {
    const { data } = await api.get(`/market/name-card/${encodeURIComponent(ticker)}`, {
      params: direction ? { direction } : undefined,
    });
    return data;
  },

  fundamentalsSnapshot: async (ticker: string): Promise<FundamentalsSnapshot> => {
    const { data } = await api.get<FundamentalsSnapshot>(
      `/market/fundamentals/${encodeURIComponent(ticker)}`,
    );
    return data;
  },

  watchlistColumns: async (symbols: string[]): Promise<WatchlistColumnRow[]> => {
    if (!symbols.length) return [];
    const { data } = await api.get<{ items: WatchlistColumnRow[] }>("/market/watchlist-columns", {
      params: { symbols: symbols.join(",") },
    });
    return data.items ?? [];
  },

  screener: async (params: MarketScreenerParams): Promise<MarketScreenerRow[]> => {
    const { data } = await api.get<{ items: MarketScreenerRow[] }>("/market/screener", { params });
    return data.items ?? [];
  },

  saveScreener: async (name: string, filters: MarketScreenerParams): Promise<void> => {
    await api.post("/market/screener/saved", { name, filters });
  },

  listSavedScreeners: async (): Promise<Array<{ name: string; filters: MarketScreenerParams }>> => {
    const { data } = await api.get<{ items: Array<{ name: string; filters: MarketScreenerParams }> }>(
      "/market/screener/saved",
    );
    return data.items ?? [];
  },

  overview: async (): Promise<Record<string, unknown>> => {
    const { data } = await api.get("/market/overview", { timeout: 45_000 });
    return data;
  },

  analysis: async (): Promise<Record<string, unknown>> => {
    const { data } = await api.get("/market/analysis", { timeout: 20_000 });
    return data;
  },

  searchUniverse: async (params: {
    q: string;
    limit?: number;
    category?: string;
    region?: string;
  }): Promise<UniverseSearchResponse> => {
    const { data } = await api.get<UniverseSearchResponse>("/market/search", { params });
    return data;
  },
};

export interface MarketScreenerParams {
  marketCapMoreThan?: number;
  marketCapLowerThan?: number;
  priceMoreThan?: number;
  priceLowerThan?: number;
  betaMoreThan?: number;
  betaLowerThan?: number;
  volumeMoreThan?: number;
  peMoreThan?: number;
  peLowerThan?: number;
  dividendMoreThan?: number;
  volMoreThan?: number;
  esMoreThan?: number;
  sector?: string;
  industry?: string;
  exchange?: string;
  country?: string;
  isEtf?: boolean;
  isActivelyTrading?: boolean;
  limit?: number;
}

export interface MarketScreenerRow {
  symbol: string;
  name?: string | null;
  exchange?: string | null;
  sector?: string | null;
  industry?: string | null;
  price?: number | null;
  market_cap?: number | null;
  beta?: number | null;
  volatility?: number | null;
  es_975?: number | null;
  volume?: number | null;
  pe?: number | null;
  dividend?: number | null;
  country?: string | null;
  is_etf?: boolean | null;
  source?: string;
  pe_status?: string | null;
  beta_status?: string | null;
  es_status?: string | null;
  fundamentals_source?: string | null;
  fundamentals_as_of?: string | null;
  risk_source?: string | null;
  currency?: string | null;
  market_cap_rub?: number | null;
}

export interface UniverseSearchHit {
  symbol: string;
  name: string;
  exchange: string;
  region: string;
  category: string;
  category_label_ru: string;
  data_tier: "full_trading" | "data_only";
  data_tier_label_ru: string;
  source: string;
  pinned: boolean;
  feed_label_ru?: string | null;
}

export interface UniverseSearchResponse {
  query: string;
  category: string;
  region: string;
  watchlist_is_pins_only: boolean;
  items: UniverseSearchHit[];
}

export interface FundamentalsSnapshot {
  symbol?: string;
  short_name?: string | null;
  sector?: string | null;
  industry?: string | null;
  exchange?: string | null;
  market_cap?: number | null;
  enterprise_value?: number | null;
  pe_ratio?: number | null;
  price_to_book?: number | null;
  price_to_sales?: number | null;
  peg?: number | null;
  ev_to_ebitda?: number | null;
  eps?: number | null;
  roe?: number | null;
  roa?: number | null;
  roic?: number | null;
  profit_margin?: number | null;
  gross_margin?: number | null;
  operating_margin?: number | null;
  net_profit_margin?: number | null;
  debt_to_equity?: number | null;
  current_ratio?: number | null;
  quick_ratio?: number | null;
  interest_coverage?: number | null;
  beta?: number | null;
  dividend_yield?: number | null;
  payout_ratio?: number | null;
  fcf_per_share?: number | null;
  revenue?: number | null;
  net_income?: number | null;
  source?: string | null;
  ratios_source?: string | null;
  metrics_source?: string | null;
}

export interface WatchlistColumnRow {
  symbol: string;
  price?: number | null;
  change_pct?: number | null;
  pe_ratio?: number | null;
  price_to_book?: number | null;
  market_cap?: number | null;
  beta?: number | null;
  rsi?: number | null;
  sma20?: number | null;
  fundamentals_source?: string | null;
  technicals_source?: string | null;
}

export interface ForecastMlSignal {
  symbol: string;
  direction: "up" | "down" | "neutral";
  confidence: number | null;
  source?: string;
  reason?: string;
}

export const directDealsApi = {
  symbols: async (params?: { q?: string; limit?: number }): Promise<DirectDealsSymbol[]> => {
    const { data } = await api.get<DirectDealsSymbol[]>("/direct-deals/symbols", {
      params,
      skipAuthRedirect: true,
    } as AxiosRequestConfig);
    return data;
  },
};

// ── Regulatory data (SEC filings, FINRA short interest) ─────────────────────

export interface RegulatoryDataResult<T = unknown> {
  success: boolean;
  data?: T | null;
  error?: string | null;
  error_code?: string | null;
  source_enabled?: boolean;
  duration_ms?: number;
  metadata?: Record<string, unknown>;
}

export interface SecFilingsPayload {
  symbol: string;
  filings: Array<{
    symbol?: string;
    form_type?: string;
    filing_date?: string | null;
    accepted_date?: string | null;
    link?: string | null;
    cik?: string | null;
  }>;
  count: number;
}

export interface FinraShortInterestPayload {
  symbol: string;
  records: Array<{
    symbol?: string;
    settlement_date?: string | null;
    current_short_position?: number | null;
    previous_short_position?: number | null;
    days_to_cover?: number | null;
    avg_daily_share_volume?: number | null;
  }>;
  count: number;
}

export const regulatoryApi = {
  status: async (): Promise<{ enabled: boolean }> => {
    const { data } = await api.get<{ enabled: boolean }>("/regulatory/status", {
      skipAuthRedirect: true,
    } as AxiosRequestConfig);
    return data;
  },

  getSecFilings: async (
    ticker: string,
    params?: { limit?: number; form_type?: string },
  ): Promise<RegulatoryDataResult<SecFilingsPayload>> => {
    const { data } = await api.get<RegulatoryDataResult<SecFilingsPayload>>(
      `/regulatory/sec-filings/${encodeURIComponent(ticker)}`,
      { params, skipAuthRedirect: true } as AxiosRequestConfig,
    );
    return data;
  },

  getFinraShortInterest: async (
    ticker: string,
    params?: { limit?: number },
  ): Promise<RegulatoryDataResult<FinraShortInterestPayload>> => {
    const { data } = await api.get<RegulatoryDataResult<FinraShortInterestPayload>>(
      `/regulatory/finra-short-interest/${encodeURIComponent(ticker)}`,
      { params, skipAuthRedirect: true } as AxiosRequestConfig,
    );
    return data;
  },
};

// ── Backtest ──────────────────────────────────────────────────────────────────

export const backtestApi = {
  run: async (params: {
    strategy: string;
    ticker: string;
    start_date: string;
    end_date: string;
    initial_capital?: number;
    parameters?: Record<string, unknown>;
  }): Promise<BacktestResult> => {
    const { data } = await api.post<BacktestResult>("/backtest/run", params);
    return data;
  },

  listRuns: async (limit = 20): Promise<BacktestResult[]> => {
    const { data } = await api.get<BacktestResult[]>("/backtest/runs", {
      params: { limit },
    });
    return data;
  },

  getRun: async (id: string): Promise<BacktestResult> => {
    const { data } = await api.get<BacktestResult>(`/backtest/runs/${id}`);
    return data;
  },
};

// ── Audit Logs ────────────────────────────────────────────────────────────────

export const auditApi = {
  list: async (params?: {
    action?: string;
    page?: number;
    page_size?: number;
  }): Promise<PaginatedResponse<AuditLog>> => {
    const { data } = await api.get<PaginatedResponse<AuditLog>>("/audit/logs", { params });
    return data;
  },
};

// ── System ────────────────────────────────────────────────────────────────────

export const systemApi = {
  health: async (): Promise<HealthStatus> => {
    const { data } = await api.get<HealthStatus>("/health");
    return data;
  },
};

// ── Ops / Pilot ───────────────────────────────────────────────────────────────

export const opsApi = {
  pilotStatus: async (): Promise<PilotStatus> => {
    const { data } = await api.get<PilotStatus>("/ops/pilot-status");
    return data;
  },

  /**
   * Trigger the kill-switch / stop drill.
   * Backend endpoint POST /ops/run-stop-drill (may be added concurrently).
   */
  runStopDrill: async (): Promise<StopDrillResult> => {
    const { data } = await api.post<StopDrillResult>("/ops/run-stop-drill");
    return data;
  },

  /**
   * Refresh per-venue balances from configured brokers.
   * Backend endpoint POST /ops/refresh-venue-balances (may be added concurrently).
   */
  refreshVenueBalances: async (): Promise<RefreshVenueBalancesResult> => {
    const { data } = await api.post<RefreshVenueBalancesResult>(
      "/ops/refresh-venue-balances",
    );
    return data;
  },

  /**
   * Kick off a market-analysis run.
   * Backend endpoint POST /ops/run-market-analysis (may be added concurrently).
   */
  runMarketAnalysis: async (): Promise<MarketAnalysisResult> => {
    const { data } = await api.post<MarketAnalysisResult>(
      "/ops/run-market-analysis",
      // «Боевой»: the server keeps only tickers the connected brokers can trade.
      { mode: currentBookMode() },
      { timeout: 45_000 },
    );
    return data;
  },

  /**
   * Flatten the paper book: close open positions + cancel approved orders,
   * freeing portfolio exposure. Backend endpoint POST /ops/close-all-positions.
   */
  closeAllPositions: async (): Promise<CloseAllPositionsResult> => {
    const { data } = await api.post<CloseAllPositionsResult>("/ops/close-all-positions");
    return data;
  },

  llmStatus: async (): Promise<LlmStatus> => {
    const { data } = await api.get<LlmStatus>("/ops/llm-status");
    return data;
  },

  connectorHealth: async () => {
    const { data } = await api.get("/ops/connector-health");
    return data;
  },

  /** Prompt 29: SLO / alerts / OpenTelemetry snapshot. */
  observe: async (): Promise<Record<string, unknown>> => {
    const { data } = await api.get<Record<string, unknown>>("/ops/observe");
    return data;
  },

  /** Prompt 29: run one ops runbook drill. */
  drill: async (name: string): Promise<Record<string, unknown>> => {
    const { data } = await api.post<Record<string, unknown>>(`/ops/observe/drill/${name}`);
    return data;
  },

  /** Prompt 30: last local checksum / in-process load measurement. */
  perf: async (): Promise<Record<string, unknown>> => {
    const { data } = await api.get<Record<string, unknown>>("/ops/perf");
    return data;
  },

  /** Prompt 30: run the local budget once. */
  runPerf: async (): Promise<Record<string, unknown>> => {
    const { data } = await api.post<Record<string, unknown>>("/ops/perf/run");
    return data;
  },
};

export const platformApi = {
  desk: async (refresh = false) => {
    const { data } = await api.get("/platform/desk", { params: { refresh } });
    return data as {
      report: Record<string, unknown>;
      ips: Record<string, unknown>;
      monitor: Record<string, unknown>;
      promotion: Record<string, unknown>;
      desks: Array<{ id: string; title: string; does: string; never: string }>;
    };
  },
  getIps: async () => {
    const { data } = await api.get("/platform/ips");
    return data as {
      user_id: string;
      deploy_cap: number | null;
      max_risk_pct: number;
      banned_tickers: string[];
      esg_keywords: string[];
      max_name_frac: number;
      updated_at: string;
    };
  },
  saveIps: async (body: {
    deploy_cap: number | null;
    max_risk_pct: number;
    banned_tickers: string[];
    esg_keywords: string[];
    max_name_frac: number;
  }) => {
    const { data } = await api.put("/platform/ips", body);
    return data;
  },
  report: async () => {
    const { data } = await api.get("/platform/report");
    return data;
  },
  monitor: async (refresh = false) => {
    const { data } = await api.get("/platform/monitor", { params: { refresh } });
    return data;
  },
  runbook: async () => {
    const { data } = await api.get("/platform/runbook");
    return data as { desks: Array<{ id: string; title: string; does: string; never: string }> };
  },
  promotion: async () => {
    const { data } = await api.get("/platform/promotion");
    return data as {
      cards: Array<Record<string, unknown>>;
      live: Record<string, unknown> | null;
      signoffs: Array<Record<string, unknown>>;
      gate_ru: string;
    };
  },
  promote: async (body: {
    name: string;
    feature_freeze_id: string;
    confirm: boolean;
    n_train: number;
    outer_n: number;
    totp_code?: string;
    note?: string;
  }) => {
    const { data } = await api.post("/platform/promote", body);
    return data;
  },
};

// ── Crypto stack / third_party integrations ───────────────────────────────────

export type CryptoIntegrationStatus = {
  name: string;
  installed: boolean;
  runnable: boolean;
  ok: boolean;
  mode?: string;
  error?: string | null;
  docs?: string | null;
  detail?: Record<string, unknown>;
};

export const cryptoStackApi = {
  integrations: async (): Promise<{
    ok: boolean;
    count: number;
    expected: string[];
    items: CryptoIntegrationStatus[];
  }> => {
    const { data } = await api.get("/crypto-stack/integrations");
    return data;
  },

  integrationStatus: async (name: string): Promise<CryptoIntegrationStatus> => {
    const { data } = await api.get(`/crypto-stack/integrations/${name}/status`);
    return data;
  },

  integrationProxy: async (name: string, path = "health") => {
    const { data } = await api.get(`/crypto-stack/integrations/${name}/proxy`, {
      params: { path },
    });
    return data;
  },

  ticker: async (symbol = "BTC/USDT"): Promise<Record<string, unknown>> => {
    const { data } = await api.get("/crypto-stack/ticker", { params: { symbol } });
    return data;
  },

  integrationAction: async (
    name: string,
    params?: {
      kind?: string;
      ticker?: string;
      path?: string;
      lamports?: number;
      symbols?: string[];
      script?: string;
    },
  ) => {
    const { symbols, kind, ticker, path, lamports, script } = params ?? {};
    const { data } = await api.post(
      `/crypto-stack/integrations/${name}/action`,
      {
        kind: kind ?? undefined,
        symbols: symbols ?? undefined,
        ticker: ticker ?? undefined,
        path: path ?? undefined,
        lamports: lamports ?? undefined,
        script: script ?? undefined,
      },
      {
        params: kind ? { kind } : undefined,
      },
    );
    return data;
  },
};

export type TradingEngineStatus = {
  name: string;
  module?: string;
  integration_mode?: string;
  license?: string;
  installed: boolean;
  runnable: boolean;
  ok: boolean;
  error?: string | null;
  github?: string;
  detail?: Record<string, unknown>;
};

export const tradingEnginesApi = {
  health: async (githubCheck = false): Promise<Record<string, unknown>> => {
    const { data } = await api.get("/trading-engines/health", {
      params: githubCheck ? { github_check: true } : undefined,
    });
    return data;
  },

  list: async (): Promise<{
    ok: boolean;
    count: number;
    expected: string[];
    items: TradingEngineStatus[];
    mcp?: Record<string, unknown>;
  }> => {
    const { data } = await api.get("/trading-engines/");
    return data;
  },

  engineAction: async (
    name: string,
    body?: { kind?: string; symbol?: string; exchange?: string; episodes?: number },
  ) => {
    const { data } = await api.post(`/trading-engines/${name}/action`, body ?? {});
    return data;
  },
};

// ── Portfolio ─────────────────────────────────────────────────────────────────

export type SampleState = {
  sample_loaded: boolean;
  has_own_positions: boolean;
  has_positions: boolean;
  accounts: Array<{ id: string; venue: string; mode: string }>;
};

export const portfolioApi = {
  metrics: async (): Promise<PortfolioMetrics> => {
    // Header switch «Учебный / Боевой»: live shows the connected broker account.
    const { data } = await api.get<PortfolioMetrics>("/portfolio/metrics", {
      skipAuthRedirect: true,
      params: { mode: currentBookMode() },
    } as AxiosRequestConfig);
    return data;
  },

  /** Per-venue balances (Binance / Finam / Tinkoff). */
  balances: async (): Promise<VenueBalancesResponse> => {
    const { data } = await api.get<VenueBalancesResponse>("/portfolio/balances", {
      skipAuthRedirect: true,
    } as AxiosRequestConfig);
    return data;
  },

  /** Recalculate TRD/BLNC from actual open positions (paper book sync). */
  refresh: async (): Promise<PortfolioRefreshResult> => {
    const { data } = await api.post<PortfolioRefreshResult>("/portfolio/refresh", undefined, {
      skipAuthRedirect: true,
    } as AxiosRequestConfig);
    return data;
  },

  /** Dashboard risk indicator with plain-language explanation. */
  riskStatus: async (): Promise<RiskStatus> => {
    const { data } = await api.get<RiskStatus>("/portfolio/risk-status", {
      skipAuthRedirect: true,
    } as AxiosRequestConfig);
    return data;
  },

  riskAnalytics: async (): Promise<PortfolioRiskAnalytics> => {
    const { data } = await api.get<PortfolioRiskAnalytics>("/portfolio/risk-analytics", {
      skipAuthRedirect: true,
    } as AxiosRequestConfig);
    return data;
  },

  riskEngine: async (user_id?: string, mode = "paper"): Promise<UnifiedRiskSnapshot> => {
    const { data } = await api.get<UnifiedRiskSnapshot>("/risk", {
      params: user_id ? { user_id, mode } : { mode },
    });
    return data;
  },

  riskWhatIf: async (body: {
    mode?: string;
    holdings?: { ticker: string; qty?: string; price?: string; ccy?: string }[];
    remove?: string[];
    add?: { ticker: string; qty?: string; price?: string; ccy?: string }[];
    set_weight?: Record<string, number>;
    add_cash_rub?: number;
  }): Promise<UnifiedRiskSnapshot> => {
    const { data } = await api.post<UnifiedRiskSnapshot>("/risk/what-if", body);
    return data;
  },

  sampleState: async (): Promise<SampleState> => {
    const { data } = await api.get<SampleState>("/portfolio/sample");
    return data;
  },

  sampleLoad: async (): Promise<SampleState> => {
    const { data } = await api.post<SampleState>("/portfolio/sample");
    return data;
  },

  sampleUnload: async (): Promise<SampleState> => {
    const { data } = await api.delete<SampleState>("/portfolio/sample");
    return data;
  },

  tax: async (mode = "paper") => {
    const { data } = await api.get("/tax", { params: { mode, resident: true } });
    return data as Record<string, unknown>;
  },

  centralBankRates: async (instruments: string[]) => {
    const { data } = await api.get("/macro/series/latest", { params: { instruments: instruments.join(",") } });
    return (data || []) as Array<{ instrument: string; value: number; unit: string; observation_time: string; period: string }>;
  },

  liquidity: async (portfolioId = "paper", participation = 0.1) => {
    const { data } = await api.get(`/portfolio/${encodeURIComponent(portfolioId)}/liquidity`, {
      params: { participation },
    });
    return data;
  },

  cashflows: async (portfolioId = "paper", params?: { from?: string; to?: string; types?: string }) => {
    const { data } = await api.get(`/portfolio/${encodeURIComponent(portfolioId)}/cashflows`, { params });
    return data;
  },

  taxDemo: async () => {
    const { data } = await api.get("/tax/demo");
    return data as {
      status?: string;
      flag?: string;
      lawyer_gate?: string;
      ytd?: { tax_base?: string | null; tax_cash?: string | null };
      harvest?: { tax_cash_reduction?: string | null; after_harvest_tax_cash?: string | null };
      positions?: Array<{
        ticker: string;
        lth_unlock_on?: string;
        tax_if_sell_today?: string | null;
        tax_if_sell_after_lth?: string | null;
        unrealized_result?: string | null;
      }>;
      iis?: { applied?: boolean; deduction_base?: string | null; tax_cash?: string | null };
      data_status?: string;
    };
  },

  cashflowSummary: async (portfolioId = "paper", months = 12) => {
    const { data } = await api.get(`/portfolio/${encodeURIComponent(portfolioId)}/cashflows/summary`, {
      params: { months },
    });
    return data;
  },

  bonds: async (portfolioId = "paper") => {
    const { data } = await api.get(`/portfolio/${encodeURIComponent(portfolioId)}/bonds`);
    return data;
  },

  bondStress: async (portfolioId = "paper", shift_bp = 100) => {
    const { data } = await api.get(`/portfolio/${encodeURIComponent(portfolioId)}/bonds/stress`, {
      params: { shift_bp },
    });
    return data;
  },

  dividendGap: async (ticker: string) => {
    const { data } = await api.get(`/dividends/${encodeURIComponent(ticker)}/gap`);
    return data;
  },

  factorReturns: async (from?: string, to?: string) => {
    const { data } = await api.get("/factors/returns", {
      params: { from, to },
    });
    return data as {
      data_status?: string;
      factors?: Record<string, number[]>;
      source?: string | null;
      as_of?: string | null;
      reason?: string | null;
    };
  },

  lookthrough: async (
    portfolioId = "me",
    mode = "paper",
    by: "issuer" | "sector" | "asset_class" | "currency" | "country" = "issuer",
    view: "lookthrough" | "broker" = "lookthrough",
  ) => {
    const { data } = await api.get(`/portfolio/${portfolioId}/lookthrough`, {
      params: { mode, by, view },
    });
    return data as {
      data_status?: string;
      reason?: string | null;
      view?: string;
      by?: string;
      rows: Array<{
        key: string;
        weight: string;
        as_of?: string | null;
        stale?: boolean;
        disclosed?: boolean;
      }>;
      hidden?: Array<{ issuer: string; lookthrough: string; direct: string; gap: string }>;
      overlaps?: Array<{ left: string; right: string; overlap: string }>;
      as_of?: string | null;
      stale?: boolean;
      source?: string | null;
    };
  },

  fundHoldings: async (figi: string) => {
    const { data } = await api.get(`/funds/${figi}/holdings`);
    return data as { data_status?: string; as_of?: string | null; holdings?: unknown[] };
  },

  keyRate: async (shiftBp = 100, mode = "paper") => {
    const { data } = await api.get("/portfolio/me/key-rate", {
      params: { shift_bp: shiftBp, mode },
    });
    return data as { sentence?: string; value_change?: number | null; income_12m?: number | null; income_note_ru?: string | null; data_status?: string };
  },

  bondCard: async (figi: string) => {
    const { data } = await api.get(`/bonds/${encodeURIComponent(figi)}`);
    return data;
  },

  portfolioFactors: async (portfolioId = "me", mode = "paper") => {
    const { data } = await api.get(`/portfolio/${portfolioId}/factors`, {
      params: { mode },
    });
    return data as {
      data_status?: string;
      reason?: string | null;
      sentence?: string;
      risk_shares?: Record<string, number | null>;
      enb?: number | null;
      enb_min_torsion?: number | null;
      n_names?: number;
      source?: string | null;
      as_of?: string | null;
      quality_note?: string | null;
    };
  },
};

export const positionAuditApi = {
  status: async (): Promise<PositionAuditStatus> => {
    const { data } = await api.get<PositionAuditStatus>("/portfolio/position-audit/status", {
      skipAuthRedirect: true,
    } as AxiosRequestConfig);
    return data;
  },

  trigger: async (): Promise<PositionAuditTriggerResult> => {
    const { data } = await api.post<PositionAuditTriggerResult>(
      "/portfolio/position-audit/trigger",
      undefined,
      { skipAuthRedirect: true } as AxiosRequestConfig,
    );
    return data;
  },

  summary: async (): Promise<PositionAuditSummary> => {
    const { data } = await api.get<PositionAuditSummary>("/portfolio/position-audit/summary", {
      skipAuthRedirect: true,
    } as AxiosRequestConfig);
    return data;
  },
};

// ── Account (personal cabinet) ────────────────────────────────────────────────

export const accountApi = {
  get: async (): Promise<AccountSummary> => {
    const { data } = await api.get<AccountSummary>("/account");
    return data;
  },

  deposit: async (amount_usd: number): Promise<PaperTransferResult> => {
    const { data } = await api.post<PaperTransferResult>("/account/deposit", { amount_usd });
    return data;
  },

  withdraw: async (amount_usd: number): Promise<PaperTransferResult> => {
    const { data } = await api.post<PaperTransferResult>("/account/withdraw", { amount_usd });
    return data;
  },

  returns: async (user_id: string, mode = "paper"): Promise<PortfolioReturns> => {
    const { data } = await api.get<PortfolioReturns>("/returns", { params: { user_id, mode, period: "inception" } });
    return data;
  },

  simpleAlts: async (user_id: string, mode = "paper"): Promise<SimpleAltResponse> => {
    const { data } = await api.get<SimpleAltResponse>("/returns/simple-alts", {
      params: { user_id, mode, period: "inception" },
    });
    return data;
  },

  decisions: async (mode = "paper") => {
    const { data } = await api.get("/portfolio/me/decisions", { params: { mode } });
    return data;
  },

  costs: async (mode = "paper") => {
    const { data } = await api.get("/portfolio/me/costs", { params: { mode } });
    return data;
  },

  pretradeCheck: async (trades: object[], mode = "paper") => {
    const { data } = await api.post("/portfolio/me/pretrade", { trades, mode });
    return data;
  },
};

// ── Settings ──────────────────────────────────────────────────────────────────

export const settingsApi = {
  get: async (): Promise<UserSettings> => {
    const { data } = await api.get<UserSettings>("/settings");
    return data;
  },

  update: async (payload: Partial<UserSettings>): Promise<UserSettings> => {
    const { data } = await api.put<UserSettings>("/settings", payload);
    return data;
  },
};

// ── News ──────────────────────────────────────────────────────────────────────

export const newsApi = {
  list: async (params?: {
    ticker?: string;
    sentiment?: string;
    page?: number;
    page_size?: number;
    locale?: string;
  }): Promise<PaginatedResponse<NewsArticle>> => {
    const { data } = await api.get<PaginatedResponse<NewsArticle>>("/news", {
      params: { locale: "ru", ...params },
    });
    return data;
  },

  fetch: async (tickers?: string[]): Promise<{ status: string; tickers: string[] }> => {
    const { data } = await api.post("/news/fetch", tickers ?? null);
    return data;
  },
};

// ── Watchlist ─────────────────────────────────────────────────────────────────

export interface WatchlistEntry {
  symbol: string;
  category: string;
  market: string;
  sector: string | null;
  label: string;
  label_ru: string;
  filter_key?: string;
}

export const watchlistApi = {
  effective: async (): Promise<{ tickers: string[]; entries: WatchlistEntry[] }> => {
    const { data } = await api.get<{ tickers: string[]; entries: WatchlistEntry[] }>(
      "/watchlists/effective",
    );
    return data;
  },

  list: async () => {
    const { data } = await api.get("/watchlists");
    return data;
  },

  create: async (name: string, tickers: string[]) => {
    const { data } = await api.post("/watchlists", { name, tickers });
    return data;
  },

  update: async (id: string, name: string, tickers: string[]) => {
    const { data } = await api.put(`/watchlists/${id}`, { name, tickers });
    return data;
  },

  delete: async (id: string) => {
    await api.delete(`/watchlists/${id}`);
  },

  pin: async (symbol: string) => {
    const { data } = await api.post<{ tickers: string[]; entries: WatchlistEntry[] }>(
      "/watchlists/pin",
      { symbol },
    );
    return data;
  },

  unpin: async (symbol: string) => {
    const { data } = await api.delete<{ tickers: string[]; entries: WatchlistEntry[] }>(
      `/watchlists/pin/${encodeURIComponent(symbol)}`,
    );
    return data;
  },
};

// ── Forecast ──────────────────────────────────────────────────────────────────

/** Core hierarchy JSON — matches health check (include_narrative=false). */
export const FORECAST_CLIENT_TIMEOUT_MS = 90_000;
/** Ensemble / macro upgrade layers — heavier path, hierarchy cached on 2nd call. */
export const FORECAST_UPGRADE_TIMEOUT_MS = 120_000;
/** LLM narrative layer — AITunnel verdict generation. */
export const FORECAST_NARRATIVE_TIMEOUT_MS = 75_000;

export const FORECAST_TIMEOUT_MESSAGE_RU =
  "Не удалось загрузить прогноз, повторите позже";
export const FORECAST_NARRATIVE_MESSAGE_RU =
  "Пояснение ИИ временно недоступно — повторите через минуту";

export const forecastApi = {
  signals: async (symbols: string[]): Promise<ForecastMlSignal[]> => {
    if (!symbols.length) return [];
    const uniq = [...new Set(symbols.map((s) => s.trim().toUpperCase()).filter(Boolean))];
    const chunkSize = 50;
    const chunks: string[][] = [];
    for (let i = 0; i < uniq.length; i += chunkSize) chunks.push(uniq.slice(i, i + chunkSize));
    const pages = await Promise.all(
      chunks.map(async (chunk) => {
        const { data } = await api.get<{ items: ForecastMlSignal[] }>("/forecast/signals", {
          params: { symbols: chunk.join(",") },
          timeout: 90_000,
        });
        return data.items ?? [];
      }),
    );
    return pages.flat();
  },

  regime: async (ticker?: string) => {
    const { data } = await api.get("/regime", { params: ticker ? { ticker } : {} });
    return data as {
      market: { label: string | null; status?: string; explain: string; ticker: string; scope: string };
      instrument: { label: string | null; status?: string; explain: string; ticker: string; scope: string } | null;
    };
  },

  unified: async (ticker: string, horizon_days = 1) => {
    const { data } = await api.get("/forecast-core", { params: { ticker, horizon_days } });
    return data as {
      ticker: string;
      direction: number;
      probability: number;
      trust: string;
      horizon_enabled: boolean;
      horizon_reason: string;
      degraded_note: string;
    };
  },

  actPropose: async (user_id = "demo", mode: "paper" | "live" = "paper") => {
    const { data } = await api.post("/act/propose", null, { params: { user_id, mode } });
    return data as {
      empty?: boolean;
      reason?: string;
      items?: Array<Record<string, unknown>>;
      skipped?: Array<{ kind: string; reason: string }>;
      model_version?: string;
      target_source?: string;
      target_book?: {
        status?: string;
        reason?: string;
        method?: string;
        target_source?: string;
        weights?: Record<string, string> | null;
        sum_weights?: string;
        tax?: { rate?: string | null };
      };
    };
  },

  actJournal: async (user_id = "demo") => {
    const { data } = await api.get("/act/journal", { params: { user_id } });
    return data as { items: Array<{ name: string; at: string; hash: string }>; source: string };
  },

  actManeuvers: async (status?: string) => {
    const { data } = await api.get("/act/maneuvers", { params: status ? { status } : {} });
    return data as { items: Array<Record<string, unknown>>; source: string };
  },

  actDecide: async (body: {
    maneuver_id: string;
    action: string;
    edits?: Record<string, string>;
    confirm?: boolean;
    reject_reason?: string;
    reject_note?: string;
  }) => {
    const { data } = await api.post("/act/decide", body);
    return data as Record<string, unknown>;
  },

  actSend: async (maneuver_id: string) => {
    const { data } = await api.post("/act/send", { maneuver_id });
    return data as Record<string, unknown>;
  },

  actExecute: async (maneuver_id: string, mode: "paper" | "live" = "paper") => {
    const { data } = await api.post("/act/execute", { maneuver_id, mode });
    return data as Record<string, unknown>;
  },

  actClose: async (maneuver_id: string) => {
    const { data } = await api.post("/act/close", { maneuver_id });
    return data as Record<string, unknown>;
  },

  actJournalPdf: async (maneuver_id: string) => {
    const { data } = await api.get(`/act/journal/${maneuver_id}/pdf`, { responseType: "blob" });
    return data as Blob;
  },

  actControl: async () => {
    const { data } = await api.get("/act/control");
    return data as {
      status?: string;
      items?: Array<{
        maneuver_id?: string;
        kind?: string;
        status?: string;
        actual_return?: string | null;
        expected_return?: string | null;
        do_nothing_return?: string | null;
        counterfactual_return?: string | null;
      }>;
    };
  },

  actSaveProfile: async (body: Record<string, string>) => {
    const { data } = await api.post("/act/profile", body);
    return data as Record<string, string>;
  },

  investmentProfileGet: async () => {
    const { data } = await api.get("/investment-profile");
    return data as Record<string, unknown> & {
      empty?: boolean;
      limits?: Record<string, string>;
      warnings?: Array<{ code: string; text: string }>;
      version?: number;
    };
  },

  investmentProfileSave: async (body: Record<string, unknown>) => {
    const { data } = await api.post("/investment-profile", body);
    return data as Record<string, unknown> & {
      limits?: Record<string, string>;
      warnings?: Array<{ code: string; text: string }>;
      version?: number;
    };
  },

  actPreview: async (body: { user_id?: string; ticker: string; qty: string; price: string; mode?: "paper" | "live" }) => {
    const { data } = await api.post("/act/preview", { user_id: "demo", mode: "paper", ...body });
    return data as { delta?: Record<string, { before: unknown; after: unknown }>; note?: string };
  },

  privacyMap: async () => {
    const { data } = await api.get("/privacy/data-map");
    return data as { items: Array<{ data: string; store: string; leaves_rf: string; ttl: string }> };
  },

  privacyExport: async () => {
    const { data } = await api.get("/privacy/export");
    return data as { secrets_included: boolean; user_id: string };
  },

  onboardingStatus: async (user_id = "demo") => {
    const { data } = await api.get("/onboarding/status", { params: { user_id } });
    return data as {
      empty?: boolean;
      path?: string;
      available?: boolean;
      reason?: string;
      stages?: string[];
      stages_done?: string[];
      error?: string | null;
      error_text?: string;
      ready_report?: boolean;
      next?: string | null;
      mode?: string;
      partial?: boolean;
    };
  },

  onboardingStart: async (user_id: string, path: string, venue?: string) => {
    const { data } = await api.post("/onboarding/start", { user_id, path, venue });
    return data as {
      empty?: boolean;
      path?: string;
      available?: boolean;
      reason?: string;
      disclose?: string;
      stages?: string[];
      stages_done?: string[];
      error?: string | null;
      error_text?: string;
      ready_report?: boolean;
      next?: string | null;
      mode?: string;
      partial?: boolean;
    };
  },

  onboardingKey: async (
    user_id: string,
    venue: string,
    opts: { accepted: boolean; withdraw_allowed?: boolean },
  ) => {
    const { data } = await api.post("/onboarding/key", { user_id, venue, ...opts });
    return data as {
      error?: string | null;
      error_text?: string;
      partial?: boolean;
      ready_report?: boolean;
      next?: string | null;
    };
  },

  onboardingSync: async (user_id = "demo") => {
    const { data } = await api.post("/onboarding/sync", { user_id });
    return data as {
      stages?: string[];
      stages_done?: string[];
      ready_report?: boolean;
      next?: string | null;
      error?: string | null;
      error_text?: string;
    };
  },

  onboardingDemo: async (user_id = "demo") => {
    const { data } = await api.post("/onboarding/demo", null, { params: { user_id } });
    return data as { ready_report?: boolean; next?: string | null; mode?: string; stages_done?: string[] };
  },

  notifications: async (user_id = "demo", event_name?: string) => {
    const { data } = await api.get("/notifications", { params: { user_id, event_name } });
    return data as { items?: Array<{ id: number; event_name: string; text: string; href?: string }>; count?: number };
  },

  qaSearch: async (q = "") => {
    const { data } = await api.get("/qa-tools/search", { params: { q } });
    return data as { items?: Array<{ label: string; href: string }> };
  },

  qaInvoke: async (name: string, user_id = "demo") => {
    const { data } = await api.post("/qa-tools/invoke", { name, user_id, mode: "paper" });
    return data as { first_screen?: { var_95?: unknown }; tool?: string };
  },

  sandboxSimulate: async (user_id = "demo", holdings?: Array<Record<string, string>>) => {
    const { data } = await api.post("/sandbox/simulate", { user_id, mode: "paper", holdings });
    return data as {
      source: string;
      empty?: boolean;
      data_status?: string;
      elapsed_ms?: number;
      disclaimer?: string;
      risk?: { var_95?: number | null };
      concentration?: { hhi?: unknown };
    };
  },

  personalLimits: async (user_id = "demo") => {
    const { data } = await api.get("/personal-limits", { params: { user_id } });
    return data as { data_status?: string; limits?: Record<string, unknown> | null };
  },

  putPersonalLimits: async (body: {
    user_id: string;
    crisis_loss?: number | null;
    concentration?: number | null;
    leverage?: number | null;
    drawdown?: number | null;
  }) => {
    const { data } = await api.put("/personal-limits", body);
    return data as { data_status?: string };
  },

  instrumentCalendar: async (user_id = "demo") => {
    const { data } = await api.get("/instrument-calendar", { params: { user_id } });
    return data as { data_status?: string; events?: unknown[]; reason?: string };
  },

  digestPreview: async (user_id = "demo") => {
    const { data } = await api.get("/digest", { params: { user_id } });
    return data as { delivery?: boolean; first_screen?: { data_status?: string }; disclaimer?: string };
  },

  privacyErase: async () => {
    const { data } = await api.post("/privacy/erase");
    return data as { erased: boolean; user_id: string };
  },

  reportPdf: async (user_id: string, mode: "paper" | "live" = "paper") => {
    const { data } = await api.get("/report/pdf", {
      params: { user_id, mode },
      responseType: "blob",
    });
    return data as Blob;
  },

  report: async (user_id = "demo", mode: "paper" | "live" = "paper") => {
    const { data } = await api.get("/report", { params: { user_id, mode } });
    return data as {
      headline: string;
      demo?: boolean;
      empty?: boolean;
      disclaimer: string;
      elapsed_ms: number;
      as_of?: string;
      first_screen?: {
        twr?: string | null;
        mwr?: string | null;
        var_95?: number | null;
        rubles_var_95?: number | null;
        traffic_light?: string | null;
        risk_status?: string | null;
        hhi?: number | null;
        crisis?: Record<string, unknown> | null;
        concentration_map?: Array<{ ticker?: string; weight?: unknown }>;
        equity_vs_benchmark?: {
          data_status?: string;
          benchmark_id?: string;
          benchmark_note?: string;
          points?: Array<{ t?: number; portfolio?: number; benchmark?: number | null }>;
        };
        events_calendar?: { data_status?: string };
        data_status?: string;
        as_of?: string;
      };
      stress?: { scenarios?: Array<Record<string, unknown>> };
      queues?: Record<string, { status?: string }>;
      changed?: string[];
      maneuver_control?: {
        status?: string;
        items?: Array<{
          maneuver_id?: string;
          kind?: string;
          actual_return?: string | null;
          expected_return?: string | null;
          do_nothing_return?: string | null;
          counterfactual_return?: string | null;
        }>;
      };
      fund?: {
        cagr?: number | null;
        max_dd?: number | null;
        sharpe?: number | null;
        monthly?: Array<{ year?: number; month?: string; return?: number }>;
        k1?: { status?: string; reason?: string };
        attribution?: { enb?: number | null; components?: Array<{ ticker?: string }> };
        data_status?: string;
      };
    };
  },
  statementDemo: async () => {
    const { data } = await api.get("/report/statement/demo");
    return data as {
      mode?: string;
      file_kept?: boolean;
      mail?: string;
      parsed?: { ok?: boolean; positions?: Array<{ ticker: string; qty: string; amount: string }> };
    };
  },
  statementUpload: async (file: File) => {
    const body = new FormData();
    body.append("file", file);
    const { data } = await api.post("/report/statement", body);
    return data as {
      mode?: string;
      parsed?: { ok?: boolean; positions?: Array<{ ticker: string; qty: string; amount: string }> };
    };
  },

  explain: async (key = "hhi") => {
    const { data } = await api.get("/explanations", { params: { key } });
    return data as { phrase: string; detail: string; learn: string };
  },

  behavior: async (user_id = "demo", mode: "paper" | "live" = "paper") => {
    const { data } = await api.get("/behavior", { params: { user_id, mode } });
    return data as { insufficient: boolean; text: string; sample_size: number };
  },

  concentration: async (user_id = "demo", mode: "paper" | "live" = "paper") => {
    const { data } = await api.get("/concentration", { params: { user_id, mode } });
    return data as {
      empty?: boolean;
      hhi?: string;
      effective_bets?: string;
      hidden_overlaps?: Array<{ asset_id: string; tickers: string[] }>;
      hidden_risks?: { credit_rating: string };
      disclaimer?: string;
    };
  },

  stress: async (user_id = "demo", mode: "paper" | "live" = "paper") => {
    const { data } = await api.get("/stress-library", { params: { user_id, mode } });
    return data as {
      disclaimer: string;
      empty: boolean;
      scenarios: Array<{ id: string; title: string; pnl_pct: number; limited_accuracy: boolean }>;
    };
  },

  modelRisk: async () => {
    const { data } = await api.get("/model-risk/status");
    return data as { user_reason: string; validation: { status: string; brier: number } };
  },

  accuracy: async () => {
    const { data } = await api.get("/forecast-accuracy");
    return data as {
      methodology: string;
      horizons: Array<{ horizon_days: number; n: number; accuracy: number; beats_naive: boolean }>;
    };
  },

  /** Core forecast: hierarchy + charts — без LLM и без тяжёлых upgrade-слоёв. */
  get: async (symbol: string): Promise<ForecastData> => {
    const { data } = await api.get<ForecastData>(
      `/forecast/${encodeURIComponent(symbol)}`,
      {
        timeout: FORECAST_CLIENT_TIMEOUT_MS,
        params: { include_llm: false, include_narrative: false },
      },
    );
    return data;
  },

  /** Ensemble, conformal, bull/base/bear, global macro — после get(). */
  getUpgradeLayers: async (symbol: string): Promise<ForecastData> => {
    const { data } = await api.get<ForecastData>(
      `/forecast/${encodeURIComponent(symbol)}`,
      {
        timeout: FORECAST_UPGRADE_TIMEOUT_MS,
        params: { include_llm: false, include_narrative: true },
      },
    );
    return data;
  },

  /** LLM narrative — вызывать после get(); заполняет scenario_disclosure AI-текстом. */
  getNarrative: async (symbol: string, explain = false): Promise<{
    symbol: string;
    llm_narrative: string | null;
    scenario_disclosure?: ForecastData["scenario_disclosure"];
    actionable_summary?: string[];
  }> => {
    const { data } = await api.get(
      `/forecast/${encodeURIComponent(symbol)}/narrative`,
      // explain=true spends AI tokens — only after the user presses «Пояснение ИИ».
      { timeout: FORECAST_NARRATIVE_TIMEOUT_MS, params: explain ? { explain: true } : undefined },
    );
    return data;
  },

  getRanks: async (): Promise<{
    items: import("@/types").MarketBeatData[];
    count: number;
    note_ru?: string;
    daily_book?: import("@/types").DailyBook | null;
    tear_sheet?: import("@/types").ForecastTearSheet | null;
  }> => {
    const { data } = await api.get("/forecast/ranks", {
      timeout: FORECAST_UPGRADE_TIMEOUT_MS,
    });
    return data;
  },

  getMarket: async (explain = false): Promise<MarketForecastData> => {
    const { data } = await api.get<MarketForecastData>("/forecast/market", {
      timeout: FORECAST_NARRATIVE_TIMEOUT_MS,
      params: explain ? { explain: true } : undefined,
    });
    return data;
  },
};

// ── Deal Intents ──────────────────────────────────────────────────────────────

export const dealIntentsApi = {
  list: async (params?: {
    status?: string;
    page?: number;
    page_size?: number;
  }): Promise<PaginatedResponse<DealIntent>> => {
    const { data } = await api.get<PaginatedResponse<DealIntent>>("/deal-intents", { params });
    return data;
  },

  get: async (id: string): Promise<DealIntent> => {
    const { data } = await api.get<DealIntent>(`/deal-intents/${id}`);
    return data;
  },

  edit: async (
    id: string,
    body: {
      target_price?: number;
      direction?: "long" | "short";
      required_confidence?: number;
      max_slippage_bps?: number;
      max_spread_bps?: number;
      time_in_force?: string;
      trigger_type?: string;
      approval_threshold?: number;
      risk_tag?: string;
      hedge_attachment_id?: string | null;
      exit_logic?: Record<string, unknown>;
      note?: string;
    },
  ): Promise<DealIntent> => {
    const { data } = await api.patch<DealIntent>(`/deal-intents/${id}`, body);
    return data;
  },

  approve: async (id: string, note?: string): Promise<{ deal_intent_id: string; message: string }> => {
    const { data } = await api.post(`/deal-intents/${id}/approve`, {
      action: "approve",
      note,
    });
    return data;
  },

  reject: async (id: string, note?: string, reason?: string): Promise<{ deal_intent_id: string; message: string }> => {
    const { data } = await api.post(`/deal-intents/${id}/reject`, {
      action: "reject",
      note,
      reason,
    });
    return data;
  },
};

// ── Asset Cockpit ─────────────────────────────────────────────────────────────

export const cockpitApi = {
  get: async (symbol: string): Promise<AssetCockpitData> => {
    const { data } = await api.get<AssetCockpitData>(
      `/cockpit/${encodeURIComponent(symbol)}`,
    );
    return data;
  },
};

// ── Strategy Composer ─────────────────────────────────────────────────────────

export const strategyComposerApi = {
  schema: async (): Promise<ComposerSchema> => {
    const { data } = await api.get<ComposerSchema>("/strategy-composer/schema");
    return data;
  },

  defaultConfig: async (): Promise<ComposerConfig> => {
    const { data } = await api.get<ComposerConfig>("/strategy-composer/default");
    return data;
  },

  load: async (): Promise<ComposerConfig> => {
    const { data } = await api.get<ComposerConfig>("/strategy-composer");
    return data;
  },

  save: async (config: ComposerConfig): Promise<ComposerConfig> => {
    const { data } = await api.put<ComposerConfig>("/strategy-composer", config);
    return data;
  },

  validate: async (config: ComposerConfig): Promise<ComposerValidationResult> => {
    const { data } = await api.post<ComposerValidationResult>(
      "/strategy-composer/validate",
      config,
    );
    return data;
  },

  compile: async (config: ComposerConfig): Promise<CompiledStrategyConfig> => {
    const { data } = await api.post<CompiledStrategyConfig>(
      "/strategy-composer/compile",
      config,
    );
    return data;
  },

  backtest: async (body: {
    config: ComposerConfig;
    symbol: string;
    lookback_days: number;
  }): Promise<ComposerBacktestResult> => {
    const { data } = await api.post<ComposerBacktestResult>(
      "/strategy-composer/backtest",
      body,
    );
    return data;
  },
};

// ── Origination / Admissions ──────────────────────────────────────────────────

export const applicationsApi = {
  requestOtp: async (body: { phone: string; turnstile_token: string }) => {
    const { data } = await api.post("/applications/request-otp", body, {
      skipAuthRedirect: true,
    } as any);
    return data as { ok: boolean; dev_otp?: string };
  },
  submit: async (body: Record<string, unknown>) => {
    const { data } = await api.post("/applications/submit", body, {
      skipAuthRedirect: true,
    } as any);
    return data;
  },
};

export const admissionsApi = {
  apply: async (body: Record<string, unknown>) => {
    const { data } = await api.post("/admissions/apply", body, {
      skipAuthRedirect: true,
    } as any);
    return data;
  },
  list: async (): Promise<{ columns: Record<string, any[]>; total: number }> => {
    const { data } = await api.get("/admissions");
    return data;
  },
  listPaginated: async (params?: {
    status?: string;
    bucket?: string;
    sort?: string;
    page?: number;
    page_size?: number;
  }): Promise<PaginatedResponse<Record<string, unknown>>> => {
    const { data } = await api.get("/admissions/list", { params });
    return data;
  },
  seedDemo: async (count = 30) => {
    const { data } = await api.post("/admissions/seed-demo", null, { params: { count } });
    return data as { created: number; requested: number };
  },
  create: async (body: Record<string, unknown>) => {
    const { data } = await api.post("/admissions", body);
    return data;
  },
  invite: async (body: { contact_email: string; contact_name?: string | null }) => {
    const { data } = await api.post("/admissions/invite", body);
    return data as {
      ok: boolean;
      existing_user: boolean;
      email: string;
      case_id: string;
      temporary_password: string | null;
      must_change_password: boolean;
    };
  },
  startTrial: async (id: string) => {
    const { data } = await api.post(`/admissions/${id}/start-trial`);
    return data;
  },
  approve: async (id: string) => {
    const { data } = await api.post(`/admissions/${id}/approve`);
    return data;
  },
  grantAdmin: async (id: string) => {
    const { data } = await api.post(`/admissions/${id}/grant-admin`);
    return data;
  },
  revokeAdmin: async (id: string) => {
    const { data } = await api.post(`/admissions/${id}/revoke-admin`);
    return data;
  },
  suspend: async (id: string) => {
    const { data } = await api.post(`/admissions/${id}/suspend`);
    return data;
  },
  reject: async (id: string, reason: string) => {
    const { data } = await api.post(`/admissions/${id}/reject`, { reason });
    return data;
  },
  changeStatus: async (id: string, status: string, reason?: string) => {
    const { data } = await api.post(`/admissions/${id}/status`, { status, reason });
    return data;
  },
  addNote: async (id: string, note: string) => {
    const { data } = await api.post(`/admissions/${id}/notes`, { note });
    return data;
  },
  exportCsvUrl: () => `${api.defaults.baseURL}/admissions/export.csv`,
  bitrixCard: async (id: string): Promise<string> => {
    const { data } = await api.get<string>(`/admissions/${id}/bitrix-card`, {
      responseType: "text" as any,
    });
    return data as unknown as string;
  },
};

export const devicesApi = {
  fingerprint: async (fingerprint: string, userAgent?: string) => {
    const { data } = await api.post("/devices/fingerprint", {
      fingerprint,
      user_agent: userAgent,
    });
    return data;
  },
  bind: async (fingerprint: string, userAgent?: string) => {
    const { data } = await api.post("/devices/bind", {
      fingerprint,
      user_agent: userAgent,
    });
    return data;
  },
};

export const accessPolicyApi = {
  me: async () => {
    const { data } = await api.get("/access-policy/me");
    return data;
  },
};

export const billingApi = {
  checkout: async (): Promise<{
    checkout_url?: string | null;
    already_paid?: boolean;
    amount_rub?: string;
    currency?: string;
  }> => {
    const { data } = await api.post("/billing/checkout");
    return data;
  },
};

export const adminFleetApi = {
  snapshot: async (params?: { limit?: number; refresh?: boolean }) => {
    const { data } = await api.get("/admin/fleet-audit", { params });
    return data;
  },
  refresh: async () => {
    const { data } = await api.post("/admin/fleet-audit/refresh");
    return data;
  },
};

export const adminSecurityApi = {
  loginCheck: async () => {
    const { data } = await api.post("/admin/login/check");
    return data;
  },
  mfaSetup: async () => {
    const { data } = await api.post("/admin/mfa/setup");
    return data;
  },
  mfaVerify: async (code: string) => {
    const { data } = await api.post("/admin/mfa/verify", { code });
    return data;
  },
  securityAudit: async (params?: {
    actor?: string;
    action?: string;
    from?: string;
    to?: string;
  }) => {
    const { data } = await api.get("/admin/security-audit", { params });
    return data;
  },
};

export const chatApi = {
  listConversations: async (params?: { related_symbol?: string }) => {
    const { data } = await api.get("/chat/conversations", { params });
    return data;
  },
  getMessages: async (conversationId: string) => {
    const { data } = await api.get(`/chat/conversations/${conversationId}/messages`);
    return data;
  },
  postMessage: async (conversationId: string, body: string) => {
    const { data } = await api.post(`/chat/conversations/${conversationId}/messages`, { body });
    return data;
  },
  createConversation: async (payload: {
    related_deal_intent_id?: string;
    related_symbol?: string;
    initial_message?: string;
  }) => {
    const { data } = await api.post("/chat/conversations", payload);
    return data;
  },
  archiveConversation: async (conversationId: string) => {
    const { data } = await api.post(`/chat/conversations/${conversationId}/archive`);
    return data;
  },
  forDealIntent: async (dealIntentId: string) => {
    const { data } = await api.post(`/chat/conversations/deal-intent/${dealIntentId}`);
    return data;
  },
  forTicker: async (symbol: string) => {
    const { data } = await api.post(`/chat/conversations/ticker/${encodeURIComponent(symbol)}`);
    return data;
  },
  askTickerAi: async (conversationId: string, body: string) => {
    const { data } = await api.post(`/chat/conversations/${conversationId}/ask-ai`, { body });
    return data;
  },
  askAdvisor: async (conversationId: string, body: string) => {
    const { data } = await api.post(`/chat/conversations/${conversationId}/ask-ai`, { body }, {
      timeout: 120_000,
    });
    return data;
  },
};

export type TradingAccountOut = {
  id: string;
  venue: string;
  provider_type?: string | null;
  account_mode: "paper" | "live";
  status: string;
  label?: string | null;
  account_display?: string | null;
  connected: boolean;
  rotation_due_at: string;
};

/** Brokers whose account is loaded into the portfolio book. */
export type BrokerVenue = "tinkoff" | "finam";

export type TinkoffSyncOut = {
  venue: string;
  mode: "paper" | "live";
  synced_at: string;
  ok: boolean;
  total_rub: number;
  accounts: {
    broker_account_id: string;
    book_account_id: string;
    name: string;
    access: "full" | "read_only";
    added: number;
    duplicates: number;
    positions: number;
    total_rub: number | null;
    reconciled: { ticker: string; qty: string }[];
    error: string | null;
  }[];
};

export type ConnectRawKeyVenue =
  | "binance"
  | "bybit"
  | "mexc"
  | "tokenized_equity"
  | "alpaca"
  | "tinkoff"
  | "tbank"
  | "finam";

export type TokenizedFallbackStatus = {
  primary_provider: "bybit" | "mexc";
  primary_healthy: boolean;
  alternate_provider?: "bybit" | "mexc" | null;
  alternate_connected: boolean;
  suggest_switch: boolean;
  message?: string | null;
};

export const tradingAccountsApi = {
  list: async () => {
    const { data } = await api.get("/trading-accounts");
    return data as {
      venues: Array<{
        venue: string;
        title: string;
        description: string;
        connection_type: string;
        setup_url?: string;
        setup_steps?: string[];
        provider_options?: Array<"bybit" | "mexc">;
        featured?: boolean;
        connected_accounts: TradingAccountOut[];
      }>;
      rotation_reminders: TradingAccountOut[];
      demo_mode_available?: boolean;
      tokenized_equity_provider?: "bybit" | "mexc";
    };
  },
  validate: async (body: {
    venue: ConnectRawKeyVenue;
    api_key: string;
    api_secret: string;
    provider_type?: "bybit" | "mexc";
    account_mode?: "paper" | "live";
    no_withdrawal_confirmed?: boolean;
    base_url?: string;
  }) => {
    const { data } = await api.post("/trading-accounts/validate", body);
    return data as { ok: boolean; error?: string; account_display?: string };
  },
  connect: async (body: {
    venue: ConnectRawKeyVenue;
    api_key: string;
    api_secret: string;
    provider_type?: "bybit" | "mexc";
    account_mode?: "paper" | "live";
    no_withdrawal_confirmed?: boolean;
    base_url?: string;
    reauth_token?: string;
  }) => {
    const { data } = await api.post("/trading-accounts/connect", body);
    return data as { ok: boolean; error?: string; account_display?: string; account?: TradingAccountOut };
  },
  connectToken: async (body: {
    venue: ConnectRawKeyVenue;
    token: string;
    account_mode?: "paper" | "live";
    no_withdrawal_confirmed?: boolean;
    reauth_token?: string;
    consent_broker?: boolean;
  }) => {
    const { data } = await api.post("/trading-accounts/connect-token", body);
    return data as { ok: boolean; error?: string; account_display?: string; account?: TradingAccountOut };
  },
  syncTinkoff: async (account_mode: "paper" | "live" = "live", full = false) => {
    const { data } = await api.post("/trading-accounts/tinkoff/sync", null, { params: { account_mode, full } });
    return data as TinkoffSyncOut;
  },
  syncBroker: async (venue: BrokerVenue, account_mode: "paper" | "live" = "live", full = false) => {
    const { data } = await api.post(`/trading-accounts/${venue}/sync`, null, { params: { account_mode, full } });
    return data as TinkoffSyncOut;
  },
  brokerAccounts: async (venue: BrokerVenue, account_mode: "paper" | "live" = "live") => {
    const { data } = await api.get(`/trading-accounts/${venue}/accounts`, { params: { account_mode } });
    return data as { accounts: { id: string; status: string; last_sync: string | null }[] };
  },
  tinkoffAccounts: async (account_mode: "paper" | "live" = "live") => {
    const { data } = await api.get("/trading-accounts/tinkoff/accounts", { params: { account_mode } });
    return data as { accounts: { id: string; status: string; last_sync: string | null }[] };
  },
  disconnect: async (venue: string, account_mode: string = "live") => {
    const { data } = await api.delete(`/trading-accounts/${venue}`, { params: { account_mode } });
    return data;
  },
  tradingKeyStatus: async () => {
    const { data } = await api.get("/trading-accounts/status");
    return data as { has_any_key: boolean; connected_venues: string[]; settings_path: string };
  },
  fallbackStatus: async (): Promise<TokenizedFallbackStatus> => {
    const { data } = await api.get("/trading-accounts/tokenized/fallback-status");
    return data;
  },
};

export default api;
