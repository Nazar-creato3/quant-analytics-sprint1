"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ExternalLink, Link2, ShieldCheck, Unlink } from "lucide-react";
import { useState } from "react";
import { toast } from "react-hot-toast";
import { useAuth, useAccessPolicy, useHealth } from "@/hooks";
import { tradingAccountsApi, twoFactorApi, type ConnectRawKeyVenue, type BrokerVenue, type TinkoffSyncOut, type TradingAccountOut } from "@/lib/api";
import { resolveReauthToken } from "@/lib/two-factor-reauth";
import { TokenizedEquitiesOnboarding } from "@/components/trading/TokenizedEquitiesOnboarding";
import { TradingDisclosuresInline } from "@/components/trading/TradingDisclosuresModal";

/** Server detail (already in Russian) instead of the raw "status code 403" text. */
export function connectErrorText(e: unknown): string {
  const detail = (e as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
  if (typeof detail === "string" && detail.trim()) return detail;
  return "Не удалось подключить счёт. Проверьте токен и код 2FA и повторите.";
}

const BYBIT_TESTNET_SETUP_URL = "https://testnet.bybit.com/app/user/api-management";

const VENUE_LABELS: Record<string, string> = {
  bybit: "Bybit (Tokenized US)",
  tokenized_equity: "Bybit Tokenized US Equities",
  binance: "Binance",
  alpaca: "Alpaca (US stocks)",
  tinkoff: "T-Bank Invest",
  finam: "Finam",
};

function useTwoFactorEnabled() {
  return useQuery({
    queryKey: ["two-factor-status"],
    queryFn: twoFactorApi.status,
    staleTime: 60_000,
  });
}

function TotpReauthField({
  enabled,
  value,
  onChange,
}: {
  enabled: boolean;
  value: string;
  onChange: (v: string) => void;
}) {
  if (!enabled) return null;
  return (
    <div className="space-y-1">
      <label className="text-[10px] uppercase tracking-wide text-qa-muted">Код 2FA для подтверждения</label>
      <input
        inputMode="numeric"
        maxLength={6}
        value={value}
        onChange={(e) => onChange(e.target.value.replace(/\D/g, "").slice(0, 6))}
        className="input w-full text-sm text-center tracking-[0.3em]"
        placeholder="000000"
      />
    </div>
  );
}

function BybitTokenizedConnectForm({
  setupUrl,
  serverIp,
  onSuccess,
  liveAllowed,
}: {
  setupUrl?: string | null;
  serverIp?: string | null;
  onSuccess: () => void;
  liveAllowed: boolean;
}) {
  const [apiKey, setApiKey] = useState("");
  const [apiSecret, setApiSecret] = useState("");
  const [accountMode, setAccountMode] = useState<"live" | "paper">("paper");
  const [confirmed, setConfirmed] = useState(false);
  const [totp, setTotp] = useState("");
  const { data: twoFa } = useTwoFactorEnabled();
  const twoFaOn = Boolean(twoFa?.enabled);

  const basePayload = {
    venue: "tokenized_equity" as const,
    provider_type: "bybit" as const,
    api_key: apiKey,
    api_secret: apiSecret,
    account_mode: accountMode,
    no_withdrawal_confirmed: confirmed,
    base_url: accountMode === "paper" ? "https://api-testnet.bybit.com" : undefined,
  };

  const validateMutation = useMutation({
    mutationFn: () => tradingAccountsApi.validate(basePayload),
    onSuccess: (data) => {
      if (data?.ok) toast.success(`Ключ действителен: ${data.account_display}`);
      else toast.error(data?.error || "Ключ не прошёл проверку");
    },
  });

  const connectMutation = useMutation({
    mutationFn: async () => {
      const reauth_token = await resolveReauthToken(twoFaOn, totp);
      return tradingAccountsApi.connect({ ...basePayload, reauth_token });
    },
    onSuccess: (data) => {
      if (data?.ok) {
        toast.success(data.account_display ? `Счёт подключён: ${data.account_display}` : "Счёт Bybit подключён");
        setTotp("");
        onSuccess();
      } else toast.error(data?.error || "Не удалось подключить счёт");
    },
    onError: (e: unknown) => toast.error(connectErrorText(e)),
  });

  return (
    <div className="mt-3 space-y-3 border-t border-white/10 pt-3">
      <p className="text-xs text-qa-muted">
        Подключить <strong className="text-white/80">Bybit</strong> API key for tokenized US equities. Use{" "}
        <strong className="text-white/80">Учебный / тестовый</strong> for validation without live funds.
      </p>

      <div className="flex gap-2 text-xs">
        <button
          type="button"
          className={`px-2 py-1 rounded ${accountMode === "live" ? "bg-emerald-600/30" : "bg-white/5"} ${!liveAllowed ? "opacity-40 cursor-not-allowed" : ""}`}
          disabled={!liveAllowed}
          onClick={() => liveAllowed && setAccountMode("live")}
        >
          Боевой
        </button>
        <button
          type="button"
          className={`px-2 py-1 rounded ${accountMode === "paper" ? "bg-amber-600/30" : "bg-white/5"}`}
          onClick={() => setAccountMode("paper")}
        >
          Учебный / тестовый
        </button>
      </div>

      {!liveAllowed && (
        <p className="text-xs text-qa-muted">
          Боевой счёт сейчас не подключается: на платформе работает только учебный режим.
        </p>
      )}
      {accountMode === "paper" && (
        <div className="text-xs bg-amber-950/30 border border-amber-500/20 rounded px-3 py-2">
          Paper mode uses Bybit testnet (<code className="text-amber-200">api-testnet.bybit.com</code>).
        </div>
      )}
      {setupUrl ? (
        <a href={setupUrl} target="_blank" rel="noreferrer" className="text-xs text-sky-300 inline-flex items-center gap-1">
          Open Bybit API management <ExternalLink size={12} />
        </a>
      ) : (
        <a href={BYBIT_TESTNET_SETUP_URL} target="_blank" rel="noreferrer" className="text-xs text-sky-300 inline-flex items-center gap-1">
          Открыть настройки API Bybit (тестовая сеть) <ExternalLink size={12} />
        </a>
      )}
      {serverIp ? <p className="text-[10px] text-qa-muted">Если биржа требует, добавьте IP сервера в список разрешённых: {serverIp}</p> : null}
      <input type="text" placeholder="API-ключ" className="input w-full text-sm" value={apiKey} onChange={(e) => setApiKey(e.target.value)} />
      <input type="password" placeholder="Секретный ключ" className="input w-full text-sm" value={apiSecret} onChange={(e) => setApiSecret(e.target.value)} />
      <label className="flex items-start gap-2 text-xs text-qa-muted cursor-pointer">
        <input type="checkbox" checked={confirmed} onChange={(e) => setConfirmed(e.target.checked)} className="mt-0.5" />
        <span>Ключ только для торговли, без права вывода средств</span>
      </label>
      <TotpReauthField enabled={twoFaOn} value={totp} onChange={setTotp} />
      <div className="flex gap-2">
        <button type="button" className="btn-secondary text-sm flex-1" disabled={validateMutation.isPending} onClick={() => validateMutation.mutate()}>
          Проверить
        </button>
        <button type="button" className="btn-primary text-sm flex-1" disabled={connectMutation.isPending || !confirmed} onClick={() => connectMutation.mutate()}>
          Подключить
        </button>
      </div>
    </div>
  );
}

function ConnectSetupGuide({
  steps,
  setupUrl,
}: {
  steps?: string[];
  setupUrl?: string | null;
}) {
  if (!steps?.length && !setupUrl) return null;
  return (
    <div className="text-xs bg-white/5 border border-white/10 rounded-lg px-3 py-2 space-y-2">
      {steps?.length ? (
        <ol className="list-decimal list-inside space-y-1 text-qa-muted">
          {steps.map((step) => (
            <li key={step}>{step}</li>
          ))}
        </ol>
      ) : null}
      {setupUrl && (
        <a href={setupUrl} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 text-emerald-400 hover:underline">
          Инструкция <ExternalLink size={12} />
        </a>
      )}
    </div>
  );
}

function GenericConnectForm({
  venue,
  connectionType,
  setupUrl,
  setupSteps,
  onSuccess,
  liveAllowed,
}: {
  venue: string;
  connectionType: string;
  setupUrl?: string | null;
  setupSteps?: string[];
  onSuccess: () => void;
  liveAllowed: boolean;
}) {
  const [apiKey, setApiKey] = useState("");
  const [apiSecret, setApiSecret] = useState("");
  const [token, setToken] = useState("");
  const broker = brokerVenueOf(venue);
  // A broker token defaults to the real account: with «Учебный» the same T-Bank token
  // opens a broker sandbox with virtual money, which looked like "still the demo account".
  const [accountMode, setAccountMode] = useState<"live" | "paper">(broker ? "live" : "paper");
  const [confirmed, setConfirmed] = useState(false);
  const [consentBroker, setConsentBroker] = useState(false);
  const [totp, setTotp] = useState("");
  const { data: twoFa } = useTwoFactorEnabled();
  const twoFaOn = Boolean(twoFa?.enabled);
  // A live broker token is useful for viewing the real portfolio even while trading is off.
  const liveOk = liveAllowed || broker !== null;
  const sync = useBrokerSync(onSuccess);

  const connectMutation = useMutation({
    mutationFn: async () => {
      const reauth_token = await resolveReauthToken(twoFaOn, totp);
      if (connectionType === "oauth" && venue === "alpaca") {
        window.location.href = `/api/v1/trading-accounts/alpaca/authorize?account_mode=${accountMode}`;
        return null;
      }
      if (connectionType === "token") {
        return tradingAccountsApi.connectToken({
          venue: venue as ConnectRawKeyVenue,
          token,
          account_mode: accountMode,
          no_withdrawal_confirmed: confirmed,
          reauth_token,
          consent_broker: consentBroker,
        });
      }
      return tradingAccountsApi.connect({
        venue: venue as ConnectRawKeyVenue,
        api_key: apiKey,
        api_secret: apiSecret,
        account_mode: accountMode,
        no_withdrawal_confirmed: confirmed,
        reauth_token,
      });
    },
    onSuccess: (data) => {
      if (data?.ok) {
        toast.success(data.account_display ? `Счёт подключён: ${data.account_display}` : "Счёт подключён");
        setTotp("");
        setToken("");
        onSuccess();
        if (broker) sync.mutate({ venue: broker, mode: accountMode });
      } else if (data && !data.ok) toast.error(data.error || "Не удалось подключить счёт");
    },
    onError: (e: unknown) => toast.error(connectErrorText(e)),
  });

  return (
    <div className="mt-3 space-y-3 border-t border-white/10 pt-3">
      <ConnectSetupGuide steps={setupSteps} setupUrl={setupUrl} />
      <div className="flex gap-2 text-xs">
        <button
          type="button"
          className={`px-2 py-1 rounded ${accountMode === "live" ? "bg-emerald-600/30" : "bg-white/5"} ${!liveOk ? "opacity-40 cursor-not-allowed" : ""}`}
          disabled={!liveOk}
          onClick={() => liveOk && setAccountMode("live")}
        >
          Боевой
        </button>
        <button type="button" className={`px-2 py-1 rounded ${accountMode === "paper" ? "bg-amber-600/30" : "bg-white/5"}`} onClick={() => setAccountMode("paper")}>{broker ? "Учебный (песочница брокера)" : "Учебный"}</button>
      </div>
      {connectionType === "oauth" ? (
        <button type="button" className="btn-primary text-sm" onClick={() => connectMutation.mutate()}>Подключить через Alpaca</button>
      ) : connectionType === "token" ? (
        <input type="password" placeholder="Токен" className="input w-full text-sm" value={token} onChange={(e) => setToken(e.target.value)} />
      ) : (
        <>
          <input type="text" placeholder="API-ключ" className="input w-full text-sm" value={apiKey} onChange={(e) => setApiKey(e.target.value)} />
          <input type="password" placeholder="Секретный ключ" className="input w-full text-sm" value={apiSecret} onChange={(e) => setApiSecret(e.target.value)} />
        </>
      )}
      {broker && accountMode === "live" && !liveAllowed && (
        <p className="text-xs text-qa-muted">
          Боевой счёт подключается для просмотра: портфель, операции, риск и доходность. Сделки на нём включатся, когда на платформе откроется реальная торговля.
        </p>
      )}
      {broker && (
        <label className="flex items-start gap-2 text-xs text-qa-muted cursor-pointer">
          <input
            type="checkbox"
            checked={consentBroker}
            onChange={(e) => setConsentBroker(e.target.checked)}
            className="mt-0.5"
            data-testid="consent-broker"
          />
          <span>
            Даю{" "}
            <a href="/legal/consent_broker" target="_blank" rel="noopener noreferrer" className="text-emerald-400 hover:underline">
              согласие на обработку данных брокерского счёта
            </a>
          </span>
        </label>
      )}
      {connectionType !== "oauth" && !broker && (
        <label className="flex items-start gap-2 text-xs text-qa-muted cursor-pointer">
          <input type="checkbox" checked={confirmed} onChange={(e) => setConfirmed(e.target.checked)} className="mt-0.5" />
          <span>Ключ только для торговли, без права вывода средств</span>
        </label>
      )}
      <TotpReauthField enabled={twoFaOn && connectionType !== "oauth"} value={totp} onChange={setTotp} />
      {connectionType !== "oauth" && (
        <button type="button" className="btn-primary text-sm w-full" disabled={connectMutation.isPending || sync.isPending || (broker !== null && !consentBroker)} onClick={() => connectMutation.mutate()}>
          {connectMutation.isPending ? "Проверяю токен у брокера…" : sync.isPending ? "Загружаю счёт…" : "Проверить и сохранить"}
        </button>
      )}
    </div>
  );
}

export function syncSummaryText(out: TinkoffSyncOut): string {
  const failed = out.accounts.filter((a) => a.error);
  if (failed.length && failed.length === out.accounts.length) return failed[0].error || "Не удалось загрузить счёт";
  const added = out.accounts.reduce((n, a) => n + a.added, 0);
  const positions = out.accounts.reduce((n, a) => n + a.positions, 0);
  const total = Math.round(out.total_rub).toLocaleString("ru-RU");
  const tail = failed.length ? ` Не загружено счетов: ${failed.length}.` : "";
  return `Счёт загружен: ${positions} поз., ${total} ₽, новых операций ${added}.${tail}`;
}

export function brokerVenueOf(venue: string): BrokerVenue | null {
  if (venue === "tinkoff" || venue === "tbank") return "tinkoff";
  if (venue === "finam") return "finam";
  return null;
}

function useBrokerSync(onDone?: () => void) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ venue, mode, full }: { venue: BrokerVenue; mode: "paper" | "live"; full?: boolean }) =>
      tradingAccountsApi.syncBroker(venue, mode, full),
    onSuccess: (out) => {
      if (out.accounts.some((a) => !a.error)) toast.success(syncSummaryText(out));
      else toast.error(syncSummaryText(out));
      void qc.invalidateQueries();
      onDone?.();
    },
    onError: (e: unknown) => toast.error(connectErrorText(e)),
  });
}

const MODE_LABEL: Record<string, string> = { live: "Боевой", paper: "Учебный" };

function ConnectedRow({ account, onRevoke }: { account: TradingAccountOut; onRevoke: () => void }) {
  const revoke = useMutation({
    mutationFn: () => tradingAccountsApi.disconnect(account.venue, account.account_mode),
    onSuccess: () => { toast.success("Счёт отключён"); onRevoke(); },
  });
  const sync = useBrokerSync();
  const broker = brokerVenueOf(account.venue);
  return (
    <div className="flex flex-wrap items-center justify-between gap-2 text-sm py-1">
      <div>
        <span className="text-emerald-400">{MODE_LABEL[account.account_mode] ?? account.account_mode}</span>
        {account.account_display && <span className="text-qa-muted ml-2">{account.account_display}</span>}
      </div>
      <div className="flex items-center gap-3">
        {broker && (
          <button
            type="button"
            className="text-emerald-400 hover:text-emerald-300 text-xs"
            disabled={sync.isPending}
            onClick={() => sync.mutate({ venue: broker, mode: account.account_mode })}
            data-testid="broker-sync"
          >
            {sync.isPending ? "Загружаю…" : "Обновить с брокера"}
          </button>
        )}
        <button type="button" className="text-red-400 hover:text-red-300 flex items-center gap-1" onClick={() => revoke.mutate()}>
          <Unlink size={14} /> Отключить
        </button>
      </div>
    </div>
  );
}

export function TradingAccountsPanel() {
  const qc = useQueryClient();
  const { isStaff } = useAuth();
  const { level } = useAccessPolicy();
  const { data: health } = useHealth();
  // Server rejects live keys while live trading is off, so never offer them then.
  const liveAllowed =
    health?.trading_mode === "live" &&
    (isStaff ||
      ["approved_live", "restricted_live", "managed_account", "enterprise"].includes(level ?? ""));
  const [expanded, setExpanded] = useState<string | null>("tokenized_equity");

  const { data: contentData } = useQuery({
    queryKey: ["tokenized-equities-content"],
    queryFn: async () => {
      const res = await fetch("/api/v1/tokenized-equities/content");
      return res.json();
    },
  });

  const { data, isLoading } = useQuery({ queryKey: ["trading-accounts"], queryFn: tradingAccountsApi.list });
  const refresh = () => {
    qc.invalidateQueries({ queryKey: ["trading-accounts"] });
  };

  if (isLoading) return <p className="text-sm text-qa-muted">Загрузка счетов…</p>;

  const anyConnected = (data?.venues || []).some((v) => v.connected_accounts.some((a) => a.connected));
  // Russian brokers first: the main scenario is a T-Bank / Finam account report.
  const ORDER = ["tinkoff", "finam", "tokenized_equity", "binance", "alpaca"];
  const rank = (v: string) => (ORDER.indexOf(v) < 0 ? 99 : ORDER.indexOf(v));
  const orderedVenues = [...(data?.venues || [])].sort((a, b) => rank(a.venue) - rank(b.venue));

  return (
    <div className="space-y-4">
      <section id="brokers" className="card p-5 space-y-4 scroll-mt-20">
        <div className="flex items-center gap-2">
          <ShieldCheck size={18} className="text-emerald-400" />
          <h2 className="font-semibold text-lg">Брокерские счета</h2>
        </div>
        <p className="text-xs text-qa-muted">Подключённый счёт загружается в «Портфель» в боевом режиме: позиции, операции, доход, издержки и налоги.</p>

        {!anyConnected && (
          <div className="text-xs border border-terminal-accent/40 bg-terminal-accent/10 rounded-lg px-3 py-2" data-testid="paper-until-connected">
            Пока не подключён ни один счёт, сделки исполняются на учебном (виртуальном) счёте.
          </div>
        )}

        {data?.rotation_reminders?.length ? (
          <div className="alert-warning text-xs px-3 py-2 rounded-lg">
            Пора обновить ключи (прошло 90 дней): {data.rotation_reminders.map((r) => r.venue).join(", ")}
          </div>
        ) : null}

        <div className="space-y-3">
          {orderedVenues.map((card) => {
            const connected = card.connected_accounts.filter((a) => a.connected);
            const isOpen = expanded === card.venue;
            const isTokenized = card.venue === "tokenized_equity";
            const featured = card.featured || isTokenized;
            return (
              <div key={card.venue} className={`border rounded-xl p-4 ${featured ? "border-emerald-500/30 bg-emerald-950/10" : "border-white/10"}`}>
                <div className="flex items-center justify-between">
                  <div>
                    <p className="font-medium">{card.title || VENUE_LABELS[card.venue]}</p>
                    <p className="text-xs text-qa-muted">{card.description}</p>
                  </div>
                  <span className={`text-xs px-2 py-0.5 rounded-full ${connected.length ? "bg-emerald-600/20 text-emerald-400" : "bg-white/5 text-qa-muted"}`}>
                    {connected.length ? "подключён" : "не подключён"}
                  </span>
                </div>
                {connected.map((acc) => <ConnectedRow key={acc.id} account={acc} onRevoke={refresh} />)}
                <button type="button" className="mt-2 text-sm text-emerald-400 flex items-center gap-1" onClick={() => setExpanded(isOpen ? null : card.venue)}>
                  <Link2 size={14} />
                  {isOpen ? "Скрыть" : connected.length ? "Добавить ещё ключ" : "Подключить"}
                </button>
                {isOpen && isTokenized && (
                  <BybitTokenizedConnectForm
                    setupUrl={card.setup_url}
                    serverIp={contentData?.server_ip_for_whitelist}
                    onSuccess={refresh}
                    liveAllowed={liveAllowed}
                  />
                )}
                {isOpen && !isTokenized && (
                  <GenericConnectForm
                    venue={card.venue}
                    connectionType={card.connection_type}
                    setupUrl={card.setup_url}
                    setupSteps={card.setup_steps}
                    onSuccess={refresh}
                    liveAllowed={liveAllowed}
                  />
                )}
              </div>
            );
          })}
        </div>

        <TradingDisclosuresInline />
      </section>
      <TokenizedEquitiesOnboarding />
    </div>
  );
}
