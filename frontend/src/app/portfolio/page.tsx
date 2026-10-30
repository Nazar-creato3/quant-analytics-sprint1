"use client";

import { Suspense, useEffect, useRef } from "react";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { clsx } from "clsx";
import { Info, Link2 } from "lucide-react";
import { NavBar } from "@/components/layout/NavBar";
import { AppPageShell } from "@/components/layout/AppPageShell";
import { PageErrorBoundary } from "@/components/layout/PageErrorBoundary";
import { PortfolioRiskProfileView } from "@/components/portfolio/PortfolioRiskProfileView";
import { OverviewBlock } from "@/components/portfolio/OverviewBlock";
import { CostsBlock, DecisionsBlock, KeyRateBlock, LiquidityBlock, PayoutsBlock, TaxBlock } from "@/components/portfolio/blocks";
import { BondsPanel } from "@/components/portfolio/BondsPanel";
import { CrossActions } from "@/components/shared/CrossActions";
import { BehaviorCard } from "@/components/market/BehaviorCard";
import { ProductEvents } from "@/components/analytics/ProductEvents";
import { portfolioApi } from "@/lib/api";
import { useProductContext } from "@/contexts/ProductContext";

const TABS = [
  { id: "overview", label: "Обзор" },
  { id: "risk", label: "Риск" },
  { id: "income", label: "Доход" },
  { id: "costs", label: "Издержки и налоги" },
] as const;
type TabId = (typeof TABS)[number]["id"];

/** Shown while the portfolio is the built-in example, so nobody mistakes it for their own. */
function SampleBanner() {
  const qc = useQueryClient();
  const { mode } = useProductContext();
  const state = useQuery({ queryKey: ["pf-sample"], queryFn: portfolioApi.sampleState });
  const tried = useRef(false);
  const load = useMutation({
    mutationFn: portfolioApi.sampleLoad,
    onSuccess: () => void qc.invalidateQueries(),
  });
  const unload = useMutation({
    mutationFn: portfolioApi.sampleUnload,
    onSuccess: () => void qc.invalidateQueries(),
  });
  // Nothing to analyse yet → show the example portfolio instead of empty blocks.
  useEffect(() => {
    if (mode === "paper" && state.data && !state.data.has_positions && !state.data.sample_loaded && !tried.current) {
      tried.current = true;
      load.mutate();
    }
  }, [mode, state.data, load]);

  // The sample lives in the paper book; the live book shows only the broker's data.
  if (mode === "live" || !state.data?.sample_loaded) return null;
  return (
    <div
      className="rounded-xl border border-terminal-accent/40 bg-terminal-accent/10 px-4 py-3 flex flex-wrap items-center gap-3"
      data-testid="sample-banner"
    >
      <Info size={16} className="text-terminal-accent shrink-0" aria-hidden />
      <p className="text-sm flex-1 min-w-[220px]">
        {state.data.has_own_positions ? (
          <>Вместе с вашими позициями показан пример портфеля. Уберите его, чтобы видеть только свои.</>
        ) : (
          <>
            Это <b>пример портфеля</b>, чтобы показать, как работает аналитика. Подключите брокерский счёт — и здесь будут ваши
            бумаги.
          </>
        )}
      </p>
      <Link href="/account#brokers" className="btn-primary text-xs inline-flex items-center gap-1.5" data-testid="sample-connect">
        <Link2 size={12} aria-hidden /> Подключить брокерский счёт
      </Link>
      <button type="button" className="btn-ghost text-xs" onClick={() => unload.mutate()} disabled={unload.isPending} data-testid="sample-remove">
        Убрать пример
      </button>
    </div>
  );
}

function PortfolioTabs() {
  const params = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const raw = params.get("tab") as TabId | null;
  const tab: TabId = TABS.some((t) => t.id === raw) ? (raw as TabId) : "overview";
  const select = (id: TabId) => {
    const next = new URLSearchParams(params.toString());
    next.set("tab", id);
    next.delete("add");
    router.replace(`${pathname}?${next.toString()}`, { scroll: false });
  };

  return (
    <>
      <SampleBanner />
      <div role="tablist" aria-label="Разделы портфеля" className="flex gap-1 border-b border-cockpit-border overflow-x-auto">
        {TABS.map((t) => (
          <button
            key={t.id}
            role="tab"
            type="button"
            aria-selected={tab === t.id}
            onClick={() => select(t.id)}
            data-testid={`portfolio-tab-${t.id}`}
            className={clsx(
              "px-4 py-2 text-sm whitespace-nowrap border-b-2 -mb-px transition-colors",
              tab === t.id ? "border-terminal-accent text-qa-text font-semibold" : "border-transparent text-qa-muted hover:text-qa-text",
            )}
          >
            {t.label}
          </button>
        ))}
      </div>
      <PageErrorBoundary>
        <div role="tabpanel" className="space-y-5">
          {tab === "overview" ? (
            <>
              <ProductEvents kind="first_report_shown" />
              <OverviewBlock />
            </>
          ) : null}
          {tab === "risk" ? (
            <>
              <PortfolioRiskProfileView />
              <KeyRateBlock />
            </>
          ) : null}
          {tab === "income" ? (
            <>
              <PayoutsBlock />
              <BondsPanel portfolioId="paper" />
            </>
          ) : null}
          {tab === "costs" ? (
            <>
              <CostsBlock />
              <TaxBlock />
              <DecisionsBlock />
              <BehaviorCard />
              <LiquidityBlock />
            </>
          ) : null}
        </div>
      </PageErrorBoundary>
    </>
  );
}

export default function PortfolioPage() {
  return (
    <div className="min-h-screen bg-cockpit-bg text-qa-text flex flex-col operator-shell">
      <NavBar activeTab="portfolio" />
      <AppPageShell title="Портфель" description="Состав, риск, доход и издержки вашего портфеля на одной странице." showBack={false}>
        <Suspense fallback={null}>
          <CrossActions />
          <PortfolioTabs />
        </Suspense>
      </AppPageShell>
    </div>
  );
}
