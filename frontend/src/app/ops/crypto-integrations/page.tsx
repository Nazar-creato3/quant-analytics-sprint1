"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { OperatorDetailShell } from "@/components/operator/OperatorDetailShell";
import { cryptoStackApi, tradingEnginesApi, type CryptoIntegrationStatus, type TradingEngineStatus } from "@/lib/api";
import { useAuth } from "@/hooks";
import { clsx } from "clsx";

type HubMeta = {
  title: string;
  summary: string;
  webUi?: string;
  proxyName?: string;
  launchKind?: string;
};

const HUB: Record<string, HubMeta> = {
  "crypto-analytics-platform": {
    title: "Crypto Analytics (CAP)",
    summary: "Отдельный сервис аналитики с документацией API.",
    webUi: "http://127.0.0.1:18000/docs",
    proxyName: "crypto-analytics-platform",
  },
  "crypto-pulse-ai": {
    title: "Crypto Pulse AI",
    summary: "Vite research UI sidecar.",
    webUi: "http://127.0.0.1:5173",
  },
  "opentao-api": {
    title: "OpenTao API",
    summary: "Bittensor data API (FastAPI docs).",
    webUi: "http://127.0.0.1:3000/docs",
    proxyName: "opentao-api",
  },
  "celebrum-ai-go": {
    title: "Celebrum / NeuraTrade",
    summary: "Go trading sidecar health.",
    webUi: "http://127.0.0.1:8080/health",
    proxyName: "celebrum-ai-go",
  },
  tradingagents: {
    title: "TradingAgents",
    summary: "LLM multi-agent research (import / probe).",
  },
  cryptodevtools: {
    title: "CryptoDevTools",
    summary: "Solana/EVM helper utilities via adapter actions.",
  },
  ccxt: {
    title: "CCXT",
    summary: "Production pip exchange library (reference clone optional).",
  },
};

const ENGINE_HUB: Record<string, { title: string; summary: string; probeKind?: string }> = {
  ccxt: { title: "Данные бирж", summary: "Единый доступ к котировкам и истории.", probeKind: "exchange_count" },
  vectorbt: { title: "Быстрый прогон", summary: "Векторный расчёт поверх прогноза и манёвров.", probeKind: "sample_momentum_backtest" },
  "nautilus-trader": { title: "Событийный прогон", summary: "Прогон сценария по шагам.", probeKind: "event_driven_backtest" },
  freqtrade: { title: "Сетка", summary: "Исполнение сетки через отдельный сервис.", probeKind: "read_signal" },
  hummingbot: { title: "План сетки", summary: "Предложение параметров сетки.", probeKind: "propose_grid" },
  tradingagents: { title: "Разбор манёвра", summary: "Несколько ролей обсуждают идею.", probeKind: "debate_dry_run" },
  finrl: { title: "Обучение политики", summary: "Обучение и оценка по истории цен.", probeKind: "policy_score" },
  lumibot: { title: "Бумажный прогон", summary: "Тот же путь, что в терминале, на бумаге.", probeKind: "sample_backtest" },
};

function EngineStatusPill({ row }: { row: TradingEngineStatus }) {
  const tone = row.ok
    ? "text-terminal-up border-terminal-up/40"
    : row.runnable
      ? "text-terminal-accent border-terminal-accent/40"
      : "text-qa-muted border-qa-border-strong";
  const label = row.ok ? "готово" : row.runnable ? "частично" : row.installed ? "установлено" : "нет";
  return (
    <span className={clsx("px-1.5 py-0.5 rounded border text-[10px] tracking-wide", tone)}>
      {label}
    </span>
  );
}

function StatusPill({ row }: { row: CryptoIntegrationStatus }) {
  const label = !row.installed ? "нет" : row.runnable ? "готово" : "установлено";
  const tone = !row.installed
    ? "text-qa-muted border-qa-border-strong"
    : row.runnable
      ? "text-terminal-up border-terminal-up/40"
      : "text-terminal-accent border-terminal-accent/40";
  return (
    <span className={clsx("px-1.5 py-0.5 rounded border text-[10px] tracking-wide", tone)}>
      {label}
    </span>
  );
}

const IFRAME_PREF_KEY = "qa-integrations-show-iframe";

export default function CryptoIntegrationsPage() {
  const qc = useQueryClient();
  const router = useRouter();
  const { isAdmin, isLoading: authLoading } = useAuth();
  const [showIframePreviews, setShowIframePreviews] = useState(false);

  useEffect(() => {
    try {
      setShowIframePreviews(localStorage.getItem(IFRAME_PREF_KEY) === "1");
    } catch {
      /* ignore */
    }
  }, []);

  const toggleIframePreviews = () => {
    setShowIframePreviews((prev) => {
      const next = !prev;
      try {
        localStorage.setItem(IFRAME_PREF_KEY, next ? "1" : "0");
      } catch {
        /* ignore */
      }
      return next;
    });
  };

  useEffect(() => {
    if (!authLoading && !isAdmin) {
      router.replace("/");
    }
  }, [authLoading, isAdmin, router]);

  const q = useQuery({
    queryKey: ["crypto-stack-integrations"],
    queryFn: () => cryptoStackApi.integrations(),
    refetchInterval: 60_000,
    enabled: isAdmin,
    retry: 1,
  });

  const enginesQ = useQuery({
    queryKey: ["trading-engines"],
    queryFn: () => tradingEnginesApi.list(),
    refetchInterval: 60_000,
    enabled: isAdmin,
    retry: 1,
  });

  const engineActionMut = useMutation({
    mutationFn: ({
      name,
      kind,
      symbol,
    }: {
      name: string;
      kind?: string;
      symbol?: string;
    }) =>
      tradingEnginesApi.engineAction(
        name,
        kind || symbol ? { ...(kind ? { kind } : {}), ...(symbol ? { symbol } : {}) } : undefined,
      ),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["trading-engines"] });
    },
  });

  const actionMut = useMutation({
    mutationFn: ({ name, kind }: { name: string; kind?: string }) =>
      cryptoStackApi.integrationAction(name, kind ? { kind } : undefined),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["crypto-stack-integrations"] });
    },
  });

  const proxyMut = useMutation({
    mutationFn: (name: string) => cryptoStackApi.integrationProxy(name, "health"),
  });

  const items = q.data?.items ?? [];
  const engineItems = enginesQ.data?.items ?? [];

  if (authLoading || !isAdmin) {
    return (
      <OperatorDetailShell
        title="Integrations Hub"
        description="Admin only."
        backHref="/"
      >
        <p className="text-xs text-qa-muted p-3">
          {authLoading ? "Загрузка…" : "Перенаправление…"}
        </p>
      </OperatorDetailShell>
    );
  }

  return (
    <OperatorDetailShell
      title="Интеграции"
      description="Статус подключений, запуск и проверка. Отдельные сервисы не входят в основной стенд."
      backHref="/ops/connector-health"
    >
      <div className="mb-3 flex flex-wrap gap-3 text-xs text-qa-muted">
        <Link href="/ops/connector-health" className="text-terminal-accent hover:text-terminal-accent">
          ← Состояние связей
        </Link>
        <Link href="/terminal" className="text-terminal-accent hover:text-terminal-accent">
          Терминал →
        </Link>
        <span>
          Подключений: {q.data?.expected?.length ?? 7} · Движков: {enginesQ.data?.expected?.length ?? 8}
        </span>
        {(actionMut.isError || proxyMut.isError || engineActionMut.isError) && (
          <span className="text-terminal-down">Не удалось выполнить действие. Попробуйте позже.</span>
        )}
      </div>

      <h2 className="text-sm text-qa-text font-medium mb-2 mt-1">Торговые движки</h2>
      <p className="text-[11px] text-qa-muted mb-2">
        Дополняют существующие разделы: данные бирж, прогон сценариев, исполнение сеток, разбор манёвров.
      </p>
      <p className="text-[11px] text-qa-muted mb-2 max-w-3xl">
        <strong className="text-qa-text font-normal">Проверка</strong> — тестовый вызов: видно, отвечает ли
        подключение. Результат — внизу страницы.
        {" "}
        <strong className="text-qa-text font-normal">Проверка связи</strong> — для отдельных сервисов с HTTP:
        платформа спрашивает их состояние без открытия адреса в браузере.
      </p>
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4 mb-6">
        {engineItems.map((row) => {
          const meta = ENGINE_HUB[row.name] ?? { title: row.name, summary: "движок" };
          return (
            <article key={row.name} className="cockpit-panel p-3 flex flex-col gap-2 min-h-[140px]">
              <div className="flex items-start justify-between gap-2">
                <div>
                  <h3 className="text-sm text-qa-text font-medium">{meta.title}</h3>
                </div>
                <EngineStatusPill row={row} />
              </div>
              <p className="text-[11px] text-qa-muted flex-1">{meta.summary}</p>
              {row.error ? (
                <p className="text-[10px] text-terminal-down line-clamp-2">Сейчас недоступно</p>
              ) : null}
              <div className="flex flex-wrap gap-1.5 mt-auto">
                <button
                  type="button"
                  title="Тестовый вызов"
                  className="px-2 py-1 rounded border border-cockpit-border text-qa-text text-[10px] hover:bg-[var(--qa-hover)] disabled:opacity-40"
                  disabled={engineActionMut.isPending}
                  onClick={() =>
                    engineActionMut.mutate({ name: row.name, kind: meta.probeKind })
                  }
                >
                  Проверка
                </button>
                {row.name === "finrl" && (
                  <button
                    type="button"
                    className="px-2 py-1 rounded border border-terminal-up/40 text-terminal-up text-[10px] hover:bg-qa-success-bg disabled:opacity-40"
                    disabled={engineActionMut.isPending}
                    onClick={() =>
                      engineActionMut.mutate({ name: "finrl", kind: "train", symbol: "SPY" })
                    }
                  >
                    Train
                  </button>
                )}
                {row.github && (
                  <a
                    href={row.github}
                    target="_blank"
                    rel="noreferrer"
                    className="px-2 py-1 rounded border border-cockpit-border text-terminal-accent text-[10px] hover:bg-[var(--qa-hover)]"
                  >
                    GitHub
                  </a>
                )}
              </div>
            </article>
          );
        })}
      </div>
      {enginesQ.isLoading && <p className="text-xs text-qa-muted mb-4">Загрузка…</p>}
      {enginesQ.isError && (
        <p className="text-xs text-terminal-down mb-4">Не удалось загрузить данные.</p>
      )}

      <div className="flex flex-wrap items-center justify-between gap-2 mb-2">
        <h2 className="text-sm text-qa-text font-medium">Подключения</h2>
        <label className="flex items-center gap-2 text-[11px] text-qa-muted cursor-pointer select-none">
          <input
            type="checkbox"
            checked={showIframePreviews}
            onChange={toggleIframePreviews}
            className="rounded border-cockpit-border"
          />
          Показать встроенный iframe sidecar
        </label>
      </div>

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
        {items.map((row) => {
          const meta = HUB[row.name] ?? {
            title: row.name,
            summary: row.mode ?? "integration",
          };
          const detail = row.detail ?? {};
          const docsUi =
            typeof detail.docs_ui === "string"
              ? detail.docs_ui
              : typeof detail.dev_url === "string"
                ? detail.dev_url
                : meta.webUi;
          return (
            <article
              key={row.name}
              className="cockpit-panel p-3 flex flex-col gap-2 min-h-[160px]"
            >
              <div className="flex items-start justify-between gap-2">
                <div>
                  <h2 className="text-sm text-qa-text font-medium">{meta.title}</h2>
                </div>
                <StatusPill row={row} />
              </div>
              <p className="text-[11px] text-qa-muted flex-1">{meta.summary}</p>
              {row.error ? (
                <p className="text-[10px] text-terminal-down">Сейчас недоступно</p>
              ) : null}
              <div className="flex flex-wrap gap-1.5 mt-auto">
                {meta.launchKind && (
                  <button
                    type="button"
                    className="px-2 py-1 rounded border border-terminal-up/40 text-terminal-up text-[10px] hover:bg-qa-success-bg disabled:opacity-40"
                    disabled={actionMut.isPending || !row.runnable}
                    onClick={() =>
                      actionMut.mutate({ name: row.name, kind: meta.launchKind })
                    }
                  >
                    Запуск
                  </button>
                )}
                <button
                  type="button"
                  title="Проверить подключение"
                  className="px-2 py-1 rounded border border-cockpit-border text-qa-text text-[10px] hover:bg-[var(--qa-hover)] disabled:opacity-40"
                  disabled={actionMut.isPending}
                  onClick={() => actionMut.mutate({ name: row.name })}
                >
                  Проверка
                </button>
                {meta.proxyName && (
                  <button
                    type="button"
                    title="Проверка связи сервиса"
                    className="px-2 py-1 rounded border border-cockpit-border text-qa-text text-[10px] hover:bg-[var(--qa-hover)] disabled:opacity-40"
                    disabled={proxyMut.isPending}
                    onClick={() => proxyMut.mutate(meta.proxyName!)}
                  >
                    Проверка связи
                  </button>
                )}
                {row.docs && (
                  <a
                    href={row.docs}
                    target="_blank"
                    rel="noreferrer"
                    className="px-2 py-1 rounded border border-cockpit-border text-terminal-accent text-[10px] hover:bg-[var(--qa-hover)]"
                  >
                    Документация
                  </a>
                )}
              </div>
              {showIframePreviews &&
                docsUi &&
                row.runnable &&
                meta.proxyName !== "celebrum-ai-go" && (
                  <div className="mt-1 rounded border border-cockpit-border/60 overflow-hidden">
                    <p className="text-[10px] text-qa-muted px-2 py-1 bg-black/20 border-b border-cockpit-border/40">
                      Sidecar preview (127.0.0.1 — на prod часто пусто; X-Frame-Options может блокировать)
                    </p>
                    <iframe
                      title={`${row.name}-ui`}
                      src={docsUi}
                      className="w-full h-40 bg-black/40"
                      sandbox="allow-scripts allow-same-origin allow-forms"
                    />
                  </div>
                )}
            </article>
          );
        })}
      </div>

      {q.isLoading && <p className="p-3 text-qa-muted text-xs">Загрузка…</p>}
      {q.isError && (
        <p className="p-3 text-terminal-down text-xs">Не удалось загрузить список подключений.</p>
      )}
      {!q.isLoading && !q.isError && items.length === 0 && (
        <p className="p-3 text-qa-muted text-xs">нет данных</p>
      )}

      {(actionMut.data || proxyMut.data || engineActionMut.data) && (
        <p className="mt-3 p-3 text-[11px] cockpit-panel text-qa-muted">
          Проверка выполнена. Подробности — в журнале сервера.
        </p>
      )}
    </OperatorDetailShell>
  );
}
