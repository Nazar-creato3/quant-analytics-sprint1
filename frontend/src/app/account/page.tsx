"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { accountApi, billingApi, forecastApi } from "@/lib/api";
import { useAuth, useAccessPolicy, hasFullAccess } from "@/hooks";
import { NavBar } from "@/components/layout/NavBar";
import { toast } from "react-hot-toast";
import { clsx } from "clsx";
import {
  ArrowDownCircle,
  ArrowUpCircle,
  Clock,
  CreditCard,
  Info,
  User,
  Wallet,
  Briefcase,
} from "lucide-react";
import { ChangePasswordPanel } from "@/components/settings/ChangePasswordPanel";
import { explainTwrs } from "@/lib/returns";
import { SimpleAltPanel } from "@/components/account/SimpleAltPanel";
import { CrossActions } from "@/components/shared/CrossActions";
import { InvestmentProfileForm } from "@/components/profile/InvestmentProfileForm";
import { TradingAccountsPanel } from "@/components/settings/TradingAccountsPanel";
import { PartnerBlock } from "@/components/partners/PartnerBlock";
import { BotPaperCard } from "@/components/account/BotPaperCard";
import { SubjectRightsCard } from "@/components/account/SubjectRightsCard";
import { SubscriptionCard } from "@/components/account/SubscriptionCard";
import { ManeuverControlBlock } from "@/components/act/ManeuverControlBlock";
import { useProductContext } from "@/contexts/ProductContext";
import { queryKeys } from "@/lib/queryKeys";

function formatCountdown(totalSeconds: number): string {
  const s = Math.max(0, Math.floor(totalSeconds));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = s % 60;
  return `${h}ч ${String(m).padStart(2, "0")}м ${String(sec).padStart(2, "0")}с`;
}

function remainingFromPolicy(policy: {
  trial_remaining_seconds?: number;
  trial_expires_at?: string | null;
  show_trial_timer?: boolean;
  paid?: boolean;
  subscription_status?: string;
  access_level?: string;
} | null | undefined): number {
  if (!policy || policy.show_trial_timer === false || hasFullAccess(policy)) return 0;
  if (typeof policy.trial_remaining_seconds === "number") {
    return policy.trial_remaining_seconds;
  }
  if (policy.trial_expires_at) {
    return Math.max(0, Math.floor((Date.parse(policy.trial_expires_at) - Date.now()) / 1000));
  }
  return 0;
}

function ReturnsBlock({ userId }: { userId?: string }) {
  const { mode } = useProductContext();
  const { data } = useQuery({
    queryKey: queryKeys.returns(userId || "anonymous", mode),
    enabled: Boolean(userId),
    queryFn: () => accountApi.returns(userId as string),
  });
  if (!data) return null;
  return (
    <div className="mt-4 rounded-lg border border-cockpit-border p-3">
      <p className="text-[10px] uppercase tracking-wide text-qa-muted">Доходность</p>
      <p className="text-sm text-white mt-1">
        {data.twr_label}: {data.twr} · {data.mwr_label}: {data.mwr}
      </p>
      <p className="text-xs text-qa-muted mt-1">{explainTwrs()}</p>
      {data.incomplete && <p className="text-xs text-terminal-accent mt-1">{data.load_report_hint}</p>}
    </div>
  );
}

function formatUsd(value: number | null | undefined): string {
  if (value == null) {
    return "нет цены";
  }
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 2,
  }).format(value);
}

export default function AccountPage() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const { isStaff } = useAuth();
  const { activeTicker, mode } = useProductContext();
  const { accountNavLocked, isLoading: policyLoading, policy, fullAccess } = useAccessPolicy();
  const [depositAmount, setDepositAmount] = useState("10000");
  const [withdrawAmount, setWithdrawAmount] = useState("1000");
  const [remaining, setRemaining] = useState(0);
  const [paying, setPaying] = useState(false);

  const { data, isLoading, error } = useQuery({
    queryKey: ["account"],
    queryFn: accountApi.get,
  });
  const control = useQuery({
    queryKey: ["act-control"],
    queryFn: () => forecastApi.actControl(),
  });

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ["account"] });
    queryClient.invalidateQueries({ queryKey: ["portfolio-metrics"] });
    queryClient.invalidateQueries({ queryKey: ["settings"] });
  };

  const depositMutation = useMutation({
    mutationFn: () => accountApi.deposit(parseFloat(depositAmount)),
    onSuccess: (resp) => {
      invalidate();
      toast.success(resp.message);
    },
    onError: (err: Error & { response?: { data?: { detail?: string } } }) => {
      toast.error(err.response?.data?.detail ?? "Не удалось пополнить баланс");
    },
  });

  const withdrawMutation = useMutation({
    mutationFn: () => accountApi.withdraw(parseFloat(withdrawAmount)),
    onSuccess: (resp) => {
      invalidate();
      toast.success(resp.message);
    },
    onError: (err: Error & { response?: { data?: { detail?: string } } }) => {
      toast.error(err.response?.data?.detail ?? "Не удалось вывести средства");
    },
  });

  const balance = data?.balance;
  const user = data?.user;
  const portfolios = data?.portfolios ?? [];

  useEffect(() => {
    if (!policyLoading && accountNavLocked && !isStaff) {
      router.replace("/settings");
    }
  }, [accountNavLocked, isStaff, policyLoading, router]);

  useEffect(() => {
    if (fullAccess || policy?.show_trial_timer === false) {
      setRemaining(0);
      return;
    }
    const initial = remainingFromPolicy(policy);
    setRemaining(initial);
    if (!policy?.trial_expires_at && initial <= 0) return;
    const tick = window.setInterval(() => {
      if (policy?.trial_expires_at) {
        setRemaining(
          Math.max(0, Math.floor((Date.parse(policy.trial_expires_at) - Date.now()) / 1000)),
        );
        return;
      }
      setRemaining((prev) => Math.max(0, prev - 1));
    }, 1000);
    return () => window.clearInterval(tick);
  }, [policy, fullAccess]);

  const paid = Boolean(policy?.paid) || policy?.subscription_status === "paid" || fullAccess;
  const trialExpired = !fullAccess && (policy?.subscription_status === "trial_expired" || (!paid && remaining <= 0 && Boolean(policy?.trial_expires_at)));
  const showPaywall = !isStaff && !fullAccess && Boolean(policy?.show_trial_timer);

  if (!isStaff && (policyLoading || accountNavLocked)) {
    return (
      <div className="min-h-screen text-qa-text operator-shell">
        <NavBar activeTab="settings" />
        <main className="px-6 py-8 max-w-lg mx-auto text-sm text-qa-muted">
          <p>
            Раздел «Кабинет» недоступен для этой учётной записи. Обратитесь в поддержку.
          </p>
        </main>
      </div>
    );
  }

  return (
    <div className="min-h-screen text-qa-text operator-shell">
      <NavBar activeTab="account" />

      <main className="px-6 py-8 max-w-4xl mx-auto space-y-8">
        <div>
          <h1 className="text-lg font-semibold text-white">Личный кабинет</h1>
          <p className="text-xs text-qa-muted mt-1">Профиль, брокерские счета и баланс.</p>
        </div>
        <InvestmentProfileForm />
        <TradingAccountsPanel />
        <PartnerBlock />
        <SubscriptionCard />
        <BotPaperCard />
        <SubjectRightsCard />
        <ManeuverControlBlock
          status={control.isError ? "нет данных" : String(control.data?.status || "")}
          items={control.data?.items}
        />

        {showPaywall && (
          <div className="flex flex-col sm:flex-row sm:items-center gap-4 rounded-xl border border-cockpit-border bg-cockpit-panel-raised px-4 py-4">
            <div className="flex items-start gap-3 flex-1">
              <Clock size={16} className="shrink-0 mt-0.5 text-terminal-accent" />
              <div>
                <p className="text-sm font-semibold text-white">
                  {trialExpired ? "Пробный доступ закончился" : "Пробный доступ"}
                </p>
                <p className="text-xs text-qa-muted mt-1">
                  {trialExpired
                    ? "Оплатите подписку, чтобы продолжить работу в кабинете."
                    : "Осталось до конца пробного периода (48 часов с первого входа)."}
                </p>
                {!trialExpired && (
                  <p className="text-lg font-mono tabular text-terminal-accent mt-2">
                    {formatCountdown(remaining)}
                  </p>
                )}
              </div>
            </div>
            <button
              type="button"
              disabled={paying}
              onClick={async () => {
                setPaying(true);
                try {
                  const resp = await billingApi.checkout();
                  if (resp.already_paid) {
                    queryClient.invalidateQueries({ queryKey: ["access-policy"] });
                    toast.success("Доступ уже оплачен");
                    return;
                  }
                  if (resp.checkout_url) {
                    window.location.assign(resp.checkout_url);
                    return;
                  }
                  toast.error("Счёт не создан");
                } catch (err: Error & { response?: { data?: { detail?: string } } } | unknown) {
                  const detail =
                    err && typeof err === "object" && "response" in err
                      ? (err as { response?: { data?: { detail?: string } } }).response?.data?.detail
                      : null;
                  toast.error(typeof detail === "string" ? detail : "Оплата ещё не подключена");
                } finally {
                  setPaying(false);
                }
              }}
              className="btn-primary justify-center px-4 py-2.5"
            >
              <CreditCard size={14} />
              {paying ? "Открываем ЮKassa…" : "Оплатить"}
            </button>
          </div>
        )}

        {paid && !isStaff && (
          <div className="flex items-start gap-3 alert-success px-4 py-3 rounded-xl">
            <Info size={14} className="shrink-0 mt-0.5" />
            <span>Полный доступ активен. Живая торговля — только после подключения ваших ключей брокера.</span>
          </div>
        )}

        {balance?.is_paper && (
          <div className="flex items-start gap-3 alert-success px-4 py-3 rounded-xl">
            <Info size={14} className="shrink-0 mt-0.5" />
            <span>
              {isStaff ? (
                <>
                  Режим: <strong>Учебная торговля</strong>. Администраторский аккаунт — пополнение и вывод здесь
                  симулируются для тестирования портфеля операторов.
                </>
              ) : (
                <>
                  Демо-режим: виртуальный баланс для обучения. Реальная торговля начнётся после
                  одобрения администратором и подключения ваших API-ключей.
                </>
              )}
            </span>
          </div>
        )}

        {error && (
          <div className="text-sm alert-error rounded-xl px-4 py-3">
            Не удалось загрузить данные кабинета.
          </div>
        )}

        <section className="card p-5">
          <div className="flex items-center gap-2 mb-4">
            <User size={16} className="text-terminal-accent" />
            <h2 className="text-sm font-semibold text-white">Личные данные</h2>
          </div>
          {isLoading || !user ? (
            <p className="text-xs text-qa-muted">Загрузка…</p>
          ) : (
            <dl className="grid grid-cols-2 gap-x-6 gap-y-2 text-sm">
              <div className="flex justify-between border-b border-qa-border/60 py-1.5">
                <dt className="text-qa-muted text-xs">Имя</dt>
                <dd className="text-xs text-qa-text">{user.name}</dd>
              </div>
              <div className="flex justify-between border-b border-qa-border/60 py-1.5">
                <dt className="text-qa-muted text-xs">Email</dt>
                <dd className="text-xs font-mono text-qa-text">{user.email}</dd>
              </div>
              <div className="flex justify-between border-b border-qa-border/60 py-1.5">
                <dt className="text-qa-muted text-xs">Роль</dt>
                <dd className="text-xs text-qa-text">{user.role}</dd>
              </div>
              <div className="flex justify-between border-b border-qa-border/60 py-1.5">
                <dt className="text-qa-muted text-xs">Режим</dt>
                <dd className={clsx(
                  "text-xs font-mono font-medium",
                  balance?.mode === "paper" ? "text-terminal-up" : "text-terminal-down",
                )}>
                  {balance?.mode ?? "—"}
                </dd>
              </div>
            </dl>
          )}
        </section>

        <ChangePasswordPanel />

        <section className="card p-5">
          <div className="flex items-center gap-2 mb-4">
            <Wallet size={16} className="text-terminal-up" />
            <h2 className="text-sm font-semibold text-white">Баланс</h2>
          </div>
          {balance ? (
            <div className="grid grid-cols-3 gap-4">
              <div className="rounded-lg bg-cockpit-panel-raised border border-cockpit-border p-4">
                <p className="text-[10px] uppercase tracking-wide text-qa-muted">Всего</p>
                <p className="text-lg font-semibold tabular text-white mt-1">{formatUsd(balance.total_usd)}</p>
              </div>
              <div className="rounded-lg bg-cockpit-panel-raised border border-cockpit-border p-4">
                <p className="text-[10px] uppercase tracking-wide text-qa-muted">Свободно</p>
                <p className="text-lg font-semibold tabular text-terminal-up mt-1">{formatUsd(balance.free_usd)}</p>
              </div>
              <div className="rounded-lg bg-cockpit-panel-raised border border-cockpit-border p-4">
                <p className="text-[10px] uppercase tracking-wide text-qa-muted">В позициях</p>
                <p className="text-lg font-semibold tabular text-terminal-accent mt-1">{formatUsd(balance.locked_usd)}</p>
              </div>
            </div>
          ) : (
            <p className="text-xs text-qa-muted">Загрузка…</p>
          )}
          <ReturnsBlock userId={data?.user?.id} />
          <SimpleAltPanel userId={data?.user?.id} />
        </section>

        {balance?.is_paper && (
          <section className="card p-5">
            <h2 className="text-sm font-semibold text-white mb-1">Paper: пополнение / вывод</h2>
            <p className="text-xs text-qa-muted mb-4">Симулированные операции с виртуальным балансом</p>
            <div className="grid grid-cols-2 gap-6">
              <div>
                <label className="label" htmlFor="qa-paper-deposit">Пополнить ($)</label>
                <div className="flex gap-2">
                  <input
                    id="qa-paper-deposit"
                    type="number"
                    value={depositAmount}
                    onChange={(e) => setDepositAmount(e.target.value)}
                    className="input tabular flex-1"
                    min="1"
                    step="1000"
                  />
                  <button
                    type="button"
                    onClick={() => depositMutation.mutate()}
                    disabled={depositMutation.isPending}
                    className="btn-primary whitespace-nowrap"
                  >
                    <ArrowUpCircle size={13} />
                    Пополнить
                  </button>
                </div>
              </div>
              <div>
                <label className="label" htmlFor="qa-paper-withdraw">Вывести свободный ($)</label>
                <div className="flex gap-2">
                  <input
                    id="qa-paper-withdraw"
                    type="number"
                    value={withdrawAmount}
                    onChange={(e) => setWithdrawAmount(e.target.value)}
                    className="input tabular flex-1"
                    min="1"
                    step="100"
                  />
                  <button
                    type="button"
                    onClick={() => withdrawMutation.mutate()}
                    disabled={withdrawMutation.isPending}
                    className="btn-secondary whitespace-nowrap"
                  >
                    <ArrowDownCircle size={13} />
                    Вывести
                  </button>
                </div>
              </div>
            </div>
          </section>
        )}

        <section className="card p-5">
          <div className="flex items-center gap-2 mb-4">
            <Briefcase size={16} className="text-terminal-accent" />
            <h2 className="text-sm font-semibold text-white">Портфели</h2>
          </div>
          {portfolios.length === 0 ? (
            <p className="text-xs text-qa-muted">Нет портфелей</p>
          ) : (
            <div className="space-y-4">
              {portfolios.map((portfolio) => (
                <div
                  key={portfolio.id}
                  className="rounded-lg border border-cockpit-border bg-cockpit-panel-raised p-4"
                >
                  <div className="flex items-center justify-between mb-3">
                    <div>
                      <p className="text-sm font-medium text-white">{portfolio.name}</p>
                      <p className="text-[10px] text-qa-muted uppercase tracking-wide">
                        {portfolio.mode} · {portfolio.base_currency}
                      </p>
                    </div>
                    <p className="text-sm font-semibold tabular text-white">
                      {formatUsd(portfolio.market_value_usd)}
                    </p>
                  </div>
                  {portfolio.positions.length > 0 ? (
                    <div className="overflow-x-auto">
                      <table className="w-full text-xs">
                        <thead>
                          <tr className="text-qa-muted border-b border-qa-border">
                            <th className="text-left py-1.5 font-medium">Тикер</th>
                            <th className="text-left py-1.5 font-medium">Сторона</th>
                            <th className="text-right py-1.5 font-medium">Стоимость</th>
                          </tr>
                        </thead>
                        <tbody>
                          {portfolio.positions.map((pos) => (
                            <tr key={pos.ticker} className="border-b border-qa-border/50">
                              <td className="py-1.5 font-mono text-qa-text">{pos.ticker}</td>
                              <td className="py-1.5 text-qa-muted">{pos.side}</td>
                              <td className="py-1.5 text-right tabular text-qa-text">
                                {formatUsd(pos.market_value_usd)}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  ) : (
                    <p className="text-xs text-qa-muted">Нет открытых позиций</p>
                  )}
                </div>
              ))}
            </div>
          )}
        </section>
      </main>
    </div>
  );
}
