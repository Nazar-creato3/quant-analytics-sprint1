"use client";

import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { settingsApi, systemApi, portfolioApi } from "@/lib/api";
import { TradingAccountsPanel } from "@/components/settings/TradingAccountsPanel";
import { TwoFactorSettingsPanel } from "@/components/settings/TwoFactorSettingsPanel";
import { PrivacyPanel } from "@/components/settings/PrivacyPanel";
import { LimitsDigestPanel } from "@/components/settings/LimitsDigestPanel";
import { useAuth } from "@/hooks";
import { useOnboarding } from "@/hooks/useOnboarding";
import { WATCHLIST_QUERY_KEY } from "@/hooks/useEffectiveWatchlist";
import { extractErrorMessage } from "@/lib/errors";
import { toast } from "react-hot-toast";
import { Save, X, AlertTriangle, Info, Sun, Moon } from "lucide-react";
import { UniverseSearchField } from "@/components/search/UniverseSearchField";
import { useTheme } from "@/contexts/ThemeContext";
import { useLocale } from "@/contexts/LocaleContext";
import { NavBar } from "@/components/layout/NavBar";
import { AppPageShell } from "@/components/layout/AppPageShell";
import { clsx } from "clsx";

export default function SettingsPage() {
  const queryClient = useQueryClient();
  const { isStaff } = useAuth();
  const { startReplay, active } = useOnboarding();
  const { theme, setTheme } = useTheme();
  const { t } = useLocale();
  const { data: health } = useQuery({
    queryKey: ["health"],
    queryFn: systemApi.health,
  });

  const { data: settings, isLoading: settingsLoading } = useQuery({
    queryKey: ["settings"],
    queryFn: settingsApi.get,
  });

  const { data: portfolioMetrics } = useQuery({
    queryKey: ["portfolio-metrics", "settings-cap"],
    queryFn: portfolioApi.metrics,
  });

  const [tickers, setTickers] = useState<string[]>([]);
  const [maxRiskPct, setMaxRiskPct] = useState("2.0");
  const [portfolioSize, setPortfolioSize] = useState("100000");
  const [confidenceThreshold, setConfidenceThreshold] = useState("0.55");
  const [dailyMaxLoss, setDailyMaxLoss] = useState("5.0");

  const capMaxUsd = (() => {
    const fromSettings = settings?.cap_max_usd;
    const live =
      portfolioMetrics?.mode === "live" ? portfolioMetrics?.account_total_usd : undefined;
    const paperSum = portfolioMetrics?.total_usd;
    const candidates = [fromSettings, live, paperSum].filter(
      (n): n is number => typeof n === "number" && Number.isFinite(n) && n > 0,
    );
    if (candidates.length) return Math.max(...candidates);
    return null;
  })();

  useEffect(() => {
    if (!settings) return;
    setTickers(settings.default_watchlist);
    setMaxRiskPct(String(settings.max_risk_per_trade_pct));
    const storedCap = settings.portfolio_size;
    const capped =
      capMaxUsd != null && Number.isFinite(capMaxUsd)
        ? Math.min(storedCap, capMaxUsd)
        : storedCap;
    setPortfolioSize(String(capped));
    setConfidenceThreshold(String(settings.confidence_threshold));
    setDailyMaxLoss(String(settings.daily_max_loss_pct));
  }, [settings, capMaxUsd]);

  useEffect(() => {
    if (typeof window === "undefined") return;
    if (window.location.hash === "#two-factor") {
      window.setTimeout(() => {
        document.getElementById("two-factor")?.scrollIntoView({ behavior: "smooth", block: "start" });
      }, 200);
    }
  }, []);

  const removeTicker = (t: string) => setTickers(tickers.filter(x => x !== t));

  const saveMutation = useMutation({
    mutationFn: () =>
      settingsApi.update({
        default_watchlist: tickers,
        portfolio_size: parseFloat(portfolioSize),
        max_risk_per_trade_pct: parseFloat(maxRiskPct),
        confidence_threshold: parseFloat(confidenceThreshold),
        daily_max_loss_pct: parseFloat(dailyMaxLoss),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["settings"] });
      queryClient.invalidateQueries({ queryKey: WATCHLIST_QUERY_KEY });
      queryClient.invalidateQueries({ queryKey: ["watchlist-effective"] });
      queryClient.invalidateQueries({
        predicate: (q) =>
          Array.isArray(q.queryKey) && q.queryKey.includes("portfolio-metrics"),
      });
      toast.success("Настройки сохранены");
    },
    onError: (err) => toast.error(extractErrorMessage(err, "Не удалось сохранить настройки")),
  });

  const handleSave = () => {
    const cap = parseFloat(portfolioSize);
    if (!Number.isFinite(cap) || cap <= 0) {
      toast.error("Укажите кап больше нуля");
      return;
    }
    if (capMaxUsd != null && cap > capMaxUsd + 0.01) {
      toast.error(
        `Кап не может быть больше баланса на счетах ($${capMaxUsd.toLocaleString("en-US", { maximumFractionDigits: 2 })}).`,
      );
      return;
    }
    saveMutation.mutate();
  };

  const isLive = (portfolioMetrics?.mode ?? health?.trading_mode) === "live";

  return (
    <div className="min-h-screen text-qa-text operator-shell flex flex-col">
      <NavBar activeTab="settings" />

      <AppPageShell
        title="Настройки"
        description="Список бумаг, риск и состояние системы"
        width="md"
      >

        <TradingAccountsPanel />

        <section id="two-factor" className="page-section scroll-mt-24">
          <TwoFactorSettingsPanel />
        </section>

        {/* Trading mode warning */}
        {isLive && (
          <div className="flex items-start gap-3 alert-error text-sm px-4 py-3 rounded-xl">
            <AlertTriangle size={16} className="shrink-0 mt-0.5 text-terminal-down" />
            <div>
              <p className="font-semibold">Live Trading активен</p>
              <p className="text-xs text-terminal-down/80 mt-0.5">
                Реальные деньги под риском. Установите <code className="font-mono bg-qa-danger-bg px-1 rounded">LIVE_TRADING_ENABLED=false</code> в .env для возврата в paper mode.
              </p>
            </div>
          </div>
        )}

        {/* Paper mode info */}
        {!isLive && (
          <div className="flex items-start gap-3 alert-success px-4 py-3 rounded-xl">
            <Info size={14} className="shrink-0 mt-0.5" />
            <span>
              {isStaff ? (
                <>
                  Режим: <strong>Учебная торговля</strong>. Вы — администратор платформы: полный доступ к
                  операторскому кокпиту, CRM и одобрению маневров. Live Trading включается отдельно через ops.
                </>
              ) : (
                <>
                  Режим: <strong>Учебная торговля</strong>. Все сделки симулируются. Реальные деньги не используются.
                  Live Trading будет включён после одобрения вашей заявки.
                </>
              )}
            </span>
          </div>
        )}

        {/* Язык: пока только русский человеческий слой. Переключатель не показываем. */}

        {/* Appearance */}
        <section className="page-section">
          <h2 className="page-section-title">{t("settings.appearance")}</h2>
          <p className="page-section-desc">
            Светлая тема — альтернатива тёмной. По умолчанию используется тёмная тема.
          </p>
          <div className="flex gap-2">
            <button
              type="button"
              onClick={() => setTheme("dark")}
              className={clsx(
                "flex items-center gap-2 px-4 py-2.5 rounded-lg text-sm font-medium border transition-colors",
                theme === "dark"
                  ? "bg-qa-active border-terminal-accent/40 text-terminal-accent"
                  : "bg-qa-panel-secondary border-qa-border text-qa-muted hover:text-qa-text",
              )}
            >
              <Moon size={14} />
              Тёмная
            </button>
            <button
              type="button"
              onClick={() => setTheme("light")}
              className={clsx(
                "flex items-center gap-2 px-4 py-2.5 rounded-lg text-sm font-medium border transition-colors",
                theme === "light"
                  ? "bg-qa-active border-terminal-accent/40 text-terminal-accent"
                  : "bg-qa-panel-secondary border-qa-border text-qa-muted hover:text-qa-text",
              )}
            >
              <Sun size={14} />
              Светлая
            </button>
          </div>
        </section>

        {/* Watchlist */}
        <section className="page-section">
          <h2 className="page-section-title">Избранное</h2>
          <div className="flex flex-wrap gap-2 mb-4">
            {tickers.map(t => (
              <span
                key={t}
                className="flex items-center gap-1.5 text-xs font-mono bg-qa-panel-secondary border border-qa-border text-qa-text px-2 py-0.5 rounded"
              >
                {t}
                <button
                  onClick={() => removeTicker(t)}
                  className="text-qa-muted hover:text-terminal-down transition-colors"
                >
                  <X size={11} />
                </button>
              </span>
            ))}
          </div>
          <div className="space-y-2">
            <UniverseSearchField
              placeholder="Тикер или название компании — закрепить в Watchlist"
              chrome="compact"
              onPick={(symbol) => {
                const t = symbol.trim().toUpperCase();
                if (!t || tickers.includes(t)) return;
                setTickers([...tickers, t]);
              }}
            />
            <p className="text-xs text-qa-muted">
              Watchlist — избранное. Поиск выше идёт по всем рынкам (US, MOEX, Европа, Азия), не только по этому списку.
            </p>
          </div>
          <p className="text-xs text-qa-muted mt-2">
            {tickers.length} тикеров. Рекомендуется 5–20.
          </p>
        </section>

        {/* Risk parameters */}
        <section className="page-section">
          <h2 className="page-section-title">Параметры риска</h2>
          <p className="page-section-desc">
            Значения по умолчанию из .env. Сохранённые здесь настройки применяются при следующем запуске pipeline.
          </p>

          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="label">Кап торговли ($)</label>
              <input
                type="number"
                value={portfolioSize}
                onChange={e => {
                  const next = e.target.value;
                  if (capMaxUsd == null) {
                    setPortfolioSize(next);
                    return;
                  }
                  const n = parseFloat(next);
                  if (!Number.isFinite(n)) {
                    setPortfolioSize(next);
                    return;
                  }
                  setPortfolioSize(String(Math.min(n, capMaxUsd)));
                }}
                className="input tabular"
                min="0"
                max={capMaxUsd ?? undefined}
                step="50"
              />
              <p className="text-xs text-qa-muted mt-1">
                Сколько из баланса на счетах платформе разрешено торговать. Не больше 100% баланса
                {capMaxUsd != null
                  ? ` (сейчас $${capMaxUsd.toLocaleString("en-US", { maximumFractionDigits: 2 })}).`
                  : "."}{" "}
                Это лимит, не пополнение.
              </p>
            </div>
            <div>
              <label className="label">Макс. риск на сделку (%)</label>
              <input
                type="number"
                value={maxRiskPct}
                onChange={e => setMaxRiskPct(e.target.value)}
                className="input tabular"
                min="0.1"
                max="10"
                step="0.1"
              />
            </div>
            <div>
              <label className="label">Порог уверенности (0–1)</label>
              <input
                type="number"
                value={confidenceThreshold}
                onChange={e => setConfidenceThreshold(e.target.value)}
                className="input tabular"
                min="0.1"
                max="0.99"
                step="0.01"
              />
              <p className="text-xs text-qa-muted mt-1">
                Ниже этого значения идея не предлагается — лучше подождать.
              </p>
            </div>
            <div>
              <label className="label">Дневной лимит убытков (%)</label>
              <input
                type="number"
                value={dailyMaxLoss}
                onChange={e => setDailyMaxLoss(e.target.value)}
                className="input tabular"
                min="0.5"
                max="50"
                step="0.5"
              />
            </div>
          </div>
        </section>

        <section className="page-section">
          <h2 className="page-section-title mb-3">Знакомство с платформой</h2>
          <p className="text-xs text-qa-muted mb-3 max-w-xl">
            Короткий экскурс по разделам. Ничего нажимать не обязательно — можно закрыть в любой момент.
          </p>
          <button
            type="button"
            onClick={startReplay}
            disabled={active}
            className="btn-secondary text-xs"
          >
            Показать экскурс снова
          </button>
        </section>

        {/* System info */}
        <section className="page-section">
          <h2 className="page-section-title mb-3">Статус системы</h2>
          <dl className="grid grid-cols-2 gap-x-6 gap-y-2 text-sm">
            {[
              ["Версия API", health?.version ?? "—"],
              ["Окружение", health?.env ?? "—"],
              ["База данных", health?.db ?? "—"],
              ["Redis", health?.redis ?? "—"],
              ["Режим торговли", health?.trading_mode ?? "—"],
            ].map(([k, v]) => (
              <div key={k} className="flex justify-between border-b border-qa-border/60 py-1.5">
                <dt className="text-qa-muted text-xs">{k}</dt>
                <dd className={clsx(
                  "text-xs font-mono font-medium",
                  v === "ok" ? "text-terminal-up" :
                  v === "live" ? "text-terminal-down" :
                  v === "paper" ? "text-terminal-up" :
                  "text-qa-text"
                )}>
                  {v}
                </dd>
              </div>
            ))}
          </dl>
        </section>

        <PrivacyPanel />
        <LimitsDigestPanel />

        {/* Save */}
        <div className="flex justify-end">
          <button
            onClick={handleSave}
            disabled={saveMutation.isPending || settingsLoading}
            className="btn-primary"
          >
            <Save size={13} />
            {saveMutation.isPending ? "Сохранение…" : "Сохранить"}
          </button>
        </div>
      </AppPageShell>
    </div>
  );
}
