"use client";

import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { NavBar } from "@/components/layout/NavBar";
import { AppPageShell } from "@/components/layout/AppPageShell";
import { DataState } from "@/components/shared/DataState";
import { forecastApi } from "@/lib/api";
import { InvestmentProfileForm } from "@/components/profile/InvestmentProfileForm";
import { PartnerBlock } from "@/components/partners/PartnerBlock";
import { useProductContext } from "@/contexts/ProductContext";

const ERROR_HINTS: Record<string, string> = {
  bad_key: "Проверьте ключ на площадке и повторите подключение.",
  extra_rights: "Создайте ключ без права вывода.",
  no_history: "Можно открыть частичный отчёт.",
  venue_down: "Подождите или откройте демо.",
  sync_slow: "Частичный отчёт уже можно открыть.",
};

export default function ConnectCapitalPage() {
  const router = useRouter();
  const { activeAccount } = useProductContext();
  const [venue, setVenue] = useState("tbank");
  const status = useQuery({
    queryKey: ["onboarding", activeAccount],
    queryFn: () => forecastApi.onboardingStatus(activeAccount),
  });
  const start = useMutation({
    mutationFn: (path: "have_account" | "partner" | "try_demo") =>
      forecastApi.onboardingStart(activeAccount, path, venue),
  });
  const keyMut = useMutation({
    mutationFn: (opts: { accepted: boolean; withdraw_allowed?: boolean }) =>
      forecastApi.onboardingKey(activeAccount, venue, opts),
  });
  const syncMut = useMutation({
    mutationFn: () => forecastApi.onboardingSync(activeAccount),
  });
  const demoMut = useMutation({
    mutationFn: () => forecastApi.onboardingDemo(activeAccount),
    onSuccess: (body) => {
      if (body.next) router.push(body.next);
    },
  });

  const view = demoMut.data || syncMut.data || keyMut.data || start.data || status.data;
  const goReport = () => {
    if (view && "next" in view && view.next) router.push(view.next);
  };

  return (
    <div className="min-h-screen bg-cockpit-bg text-qa-text flex flex-col operator-shell">
      <NavBar />
      <AppPageShell title="Подключить капитал" description="Один вход: счёт, партнёр или демо. Живая торговля включается отдельно.">
        <DataState loading={status.isLoading} error={status.isError} empty={false}>
          <div className="space-y-4" data-testid="connect-capital">
            <div className="grid gap-3 md:grid-cols-3">
              <button type="button" className="btn-secondary text-sm" onClick={() => start.mutate("have_account")}>
                У меня есть счёт
              </button>
              <button type="button" className="btn-secondary text-sm" onClick={() => start.mutate("partner")}>
                Открыть счёт у партнёра
              </button>
              <button type="button" className="btn-primary text-sm" data-testid="try-demo" onClick={() => demoMut.mutate()}>
                Сначала попробовать
              </button>
            </div>
            <PartnerBlock />

            {start.data && "available" in start.data && start.data.available === false ? (
              <p className="text-xs text-qa-muted">Партнёрский путь: {start.data.reason}. Раскрытие отношений — когда путь включат.</p>
            ) : null}

            {start.data && start.data.path === "have_account" ? (
              <section className="rounded-xl border border-qa-border p-3 space-y-2">
                <label className="block text-xs text-qa-muted" htmlFor="venue">
                  Площадка
                  <input
                    id="venue"
                    className="mt-1 w-full rounded border border-qa-border bg-transparent px-2 py-1"
                    value={venue}
                    onChange={(e) => setVenue(e.target.value)}
                  />
                </label>
                <p className="text-xs text-qa-muted">Создайте ключ без вывода. Проверка прав — до синхронизации.</p>
                <button type="button" className="btn-secondary text-xs" onClick={() => keyMut.mutate({ accepted: true })}>
                  Проверить ключ
                </button>
                <button type="button" className="btn-secondary text-xs" onClick={() => syncMut.mutate()}>
                  Следующий этап синхронизации
                </button>
              </section>
            ) : null}

            {view && "stages_done" in view && Array.isArray(view.stages_done) ? (
              <ol className="text-xs text-qa-text list-decimal pl-4">
                {(
                  ("stages" in view && Array.isArray(view.stages) && view.stages.length
                    ? view.stages
                    : ["accounts", "positions", "history", "prices", "calc"]) as string[]
                ).map((s: string) => (
                  <li key={s} className={view.stages_done?.includes(s) ? "text-qa-text" : "text-qa-muted"}>
                    {s}
                    {view.stages_done?.includes(s) ? " — готово" : " — ждёт"}
                  </li>
                ))}
              </ol>
            ) : null}

            {view && "error_text" in view && view.error_text ? (
              <p className="text-xs text-qa-muted" data-testid="onboarding-error">
                {view.error_text} {view.error ? ERROR_HINTS[view.error] : ""}
              </p>
            ) : null}

            {view && "ready_report" in view && view.ready_report ? (
              <button type="button" className="btn-primary text-sm" data-testid="open-first-report" onClick={goReport}>
                Открыть первый отчёт
              </button>
            ) : null}

            <p className="text-[10px] text-qa-muted">Пробный период и оплата — конфиг Промпта 26. Ценность видна в отчёте до оплаты.</p>
            <InvestmentProfileForm />
          </div>
        </DataState>
      </AppPageShell>
    </div>
  );
}
