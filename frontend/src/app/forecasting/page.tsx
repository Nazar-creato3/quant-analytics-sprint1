"use client";

import { useQuery } from "@tanstack/react-query";
import { forecastApi, opsApi } from "@/lib/api";
import { NavBar } from "@/components/layout/NavBar";
import { AppPageShell } from "@/components/layout/AppPageShell";
import { PageErrorBoundary } from "@/components/layout/PageErrorBoundary";
import { TickerForecastDesk } from "@/components/forecasting/TickerForecastDesk";
import { useActiveTicker } from "@/contexts/ActiveTickerContext";
import { queryKeys } from "@/lib/queryKeys";
import { CrossActions } from "@/components/shared/CrossActions";
import { useLocale } from "@/contexts/LocaleContext";
import { UniverseSearchField } from "@/components/search/UniverseSearchField";
import Link from "next/link";
import { RegimeIndicator } from "@/components/market/RegimeIndicator";

function ForecastingPageContent() {
  const { activeTicker, setActiveTicker } = useActiveTicker();
  const { t } = useLocale();

  const {
    data: marketForecast,
    isLoading: marketLoading,
  } = useQuery({
    queryKey: queryKeys.forecastMarket,
    queryFn: () => forecastApi.getMarket(),
    staleTime: 120_000,
  });

  const { data: ranks } = useQuery({
    queryKey: queryKeys.forecastRanks,
    queryFn: () => forecastApi.getRanks(),
    staleTime: 180_000,
  });

  const { data: llmStatus } = useQuery({
    queryKey: ["llm-status"],
    queryFn: opsApi.llmStatus,
    staleTime: 60_000,
  });

  return (
    <AppPageShell
        title={t("forecast.title")}
        description={t("forecast.desc")}
        width="xl"
        className="flex-1 overflow-y-auto"
        headerExtra={
          <div className="flex items-center gap-3">
            <UniverseSearchField
              placeholder="Найти бумагу…"
              onPick={(symbol) => setActiveTicker(symbol)}
              showPin={false}
              chrome="compact"
            />
            <Link href="/forecast-accuracy" className="text-xs text-terminal-accent whitespace-nowrap">
              Точность прогнозов
            </Link>
          </div>
        }
      >
        <div className="space-y-6">
          <h2 className="text-xs font-semibold uppercase tracking-wide text-qa-muted">Рынок</h2>
          <RegimeIndicator ticker={activeTicker} />
          <section
            id="market-analysis"
            className="cockpit-panel p-4 scroll-mt-20"
          >
            <h2 className="text-sm font-bold uppercase tracking-wide text-terminal-accent mb-2">
              {t("forecast.market")}
            </h2>
            {marketLoading ? (
              <p className="text-sm text-qa-muted">{t("forecast.loading")}</p>
            ) : marketForecast?.llm_narrative ? (
              <div className="space-y-2 text-sm text-qa-text leading-relaxed">
                {String(marketForecast.llm_narrative)
                  .split(/\n+/)
                  .map((p) => p.trim())
                  .filter(Boolean)
                  .map((p, i) => (
                    <p key={i}>{p.replace(/^(Вердикт|Почему|Что изменит взгляд|Действие)\s*[-–—:]\s*/i, "")}</p>
                  ))}
              </div>
            ) : marketForecast?.scenario_disclosure?.paragraphs?.length ? (
              <div className="space-y-2 text-sm text-qa-text leading-relaxed">
                {marketForecast.scenario_disclosure.paragraphs.map((p, i) => (
                  <p key={i}>{p}</p>
                ))}
              </div>
            ) : marketForecast?.market_prediction_summary?.paragraphs?.length ? (
              <div className="space-y-2 text-sm text-qa-text leading-relaxed">
                {marketForecast.market_prediction_summary.paragraphs.map((p, i) => (
                  <p key={i}>{p}</p>
                ))}
              </div>
            ) : marketForecast?.market_outlook?.length ? (
              <ul className="space-y-2 text-sm text-qa-text list-disc pl-4">
                {marketForecast.market_outlook.slice(0, 3).map((item, i) => (
                  <li key={i}>
                    {typeof item === "string"
                      ? item
                      : (item as { label_ru?: string; what_happens?: string }).label_ru ||
                        (item as { what_happens?: string }).what_happens ||
                        JSON.stringify(item)}
                  </li>
                ))}
              </ul>
            ) : marketForecast?.market_prediction_summary?.missing_resources?.length ? (
              <div className="text-sm text-qa-muted space-y-2">
                <p>Макро-сводка формируется — не хватает данных:</p>
                <ul className="list-disc pl-4 text-[11px]">
                  {marketForecast.market_prediction_summary.missing_resources.slice(0, 5).map((r) => (
                    <li key={r}>{r}</li>
                  ))}
                </ul>
              </div>
            ) : llmStatus && !llmStatus.available ? (
              <p className="text-sm text-qa-muted">
                Макро-сводка недоступна — {llmStatus.message_ru}
              </p>
            ) : (
              <p className="text-sm text-qa-muted">
                Макро-сводка недоступна — повторите позже.
              </p>
            )}
          </section>

          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between pt-2">
            <h2 className="text-xs font-semibold uppercase tracking-wide text-qa-muted">
              Бумага · <span className="font-mono text-qa-text">{activeTicker}</span>
            </h2>
            <CrossActions ticker={activeTicker} />
          </div>
          <TickerForecastDesk symbol={activeTicker} />

          {ranks?.items?.length || ranks?.daily_book ? (
            <h2 className="text-xs font-semibold uppercase tracking-wide text-qa-muted pt-2">Отбор бумаг</h2>
          ) : null}
          {ranks?.items?.length ? (
            <section className="cockpit-panel p-4">
              <h2 className="text-sm font-bold uppercase tracking-wide text-terminal-accent mb-2">
                Бумаги с наибольшим шансом обогнать рынок
              </h2>
              <p className="text-xs text-qa-muted mb-3">
                Оценка от 1 до 10: вероятность того, что бумага опередит свой рынок за 20 торговых дней. Нажмите на строку, чтобы открыть прогноз по бумаге.
              </p>
              <div className="overflow-x-auto">
                <table className="w-full text-xs">
                  <thead className="text-qa-muted uppercase tracking-wide">
                    <tr>
                      <th className="text-left py-1">Тикер</th>
                      <th className="text-right">20 дн.</th>
                      <th className="text-left pl-3">Момент входа</th>
                    </tr>
                  </thead>
                  <tbody>
                    {ranks.items.slice(0, 15).map((row) => (
                      <tr
                        key={row.symbol}
                        className="border-t border-white/5 cursor-pointer hover:bg-white/5"
                        onClick={() => setActiveTicker(row.symbol)}
                      >
                        <td className="py-1.5 font-mono">{row.symbol}</td>
                        <td className="text-right font-mono">{row.score_20}</td>
                        <td className="pl-3 text-qa-muted">{row.timing_ru}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          ) : null}

          {ranks?.daily_book ? (
            <section className="cockpit-panel p-4">
              <h2 className="text-sm font-bold uppercase tracking-wide text-terminal-accent mb-2">
                Модельный портфель дня
              </h2>
              <p className="text-xs text-qa-muted mb-3">
                Учебный расчёт, не заявки: доли распределены по оценке, не более 25% на одну бумагу. В портфель попадают бумаги с оценкой от 6.
              </p>
              {ranks.daily_book.count ? (
                <table className="w-full text-xs">
                  <thead className="text-qa-muted uppercase tracking-wide">
                    <tr>
                      <th className="text-left py-1">Тикер</th>
                      <th className="text-right">Вес</th>
                      <th className="text-right">20 дн.</th>
                    </tr>
                  </thead>
                  <tbody>
                    {ranks.daily_book.holdings.map((h) => (
                      <tr
                        key={h.symbol}
                        className="border-t border-white/5 cursor-pointer hover:bg-white/5"
                        onClick={() => setActiveTicker(h.symbol)}
                      >
                        <td className="py-1.5 font-mono">{h.symbol}</td>
                        <td className="text-right font-mono">
                          {(h.weight * 100).toFixed(1)}%
                        </td>
                        <td className="text-right font-mono">{h.score_20}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              ) : (
                <p className="text-sm text-qa-muted">Сегодня ни одна бумага не набрала оценку 6 — модельный портфель пуст.</p>
              )}
              {ranks.daily_book.deflated_sharpe &&
              (ranks.daily_book.deflated_sharpe.n || 0) > 0 ? (
                <p className="text-[10px] text-qa-muted mt-2">
                  Поправленный коэффициент Шарпа: {ranks.daily_book.deflated_sharpe.dsr?.toFixed(2)} (дней в расчёте: {ranks.daily_book.deflated_sharpe.n})
                </p>
              ) : (
            <p className="text-[10px] text-qa-muted mt-2">
                  Оценка «насколько это лучше рынка» появится после нескольких закрытых дней по сохранённым ценам.
                </p>
              )}
            </section>
          ) : null}

          {ranks?.tear_sheet ? (
        <section className="cockpit-panel p-4">
              <h2 className="text-sm font-bold uppercase tracking-wide text-terminal-accent mb-2">
                Как модельный портфель показал себя на истории
              </h2>
              <p className="text-xs text-qa-muted mb-3">
                Разбор учебных идей по сохранённым ценам, не брокерский счёт.
              </p>
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-xs">
                <div>
                  <div className="text-qa-muted">на дату</div>
                  <div className="font-mono">{ranks.tear_sheet.as_of || "—"}</div>
                </div>
                <div>
                  <div className="text-qa-muted">сверх рынка</div>
                  <div className="font-mono">
                    {ranks.tear_sheet.excess == null
                      ? "ещё мало закрытых дней"
                      : `${(ranks.tear_sheet.excess * 100).toFixed(2)}%`}
                  </div>
                </div>
                <div>
                  <div className="text-qa-muted">насколько оценка совпадала с фактом</div>
                  <div>
                    {ranks.tear_sheet.ece?.n
                      ? ranks.tear_sheet.ece.reliable
                        ? "пока похоже на правду"
                        : "оценки расходились с фактом"
                      : "мало проверенных идей"}
                  </div>
                </div>
                <div>
                  <div className="text-qa-muted">как часто меняли состав</div>
                  <div className="font-mono">
                    {ranks.tear_sheet.turnover == null
                      ? "нужен вчерашний состав"
                      : `${(ranks.tear_sheet.turnover * 100).toFixed(1)}%`}
                  </div>
                </div>
              </div>
            </section>
          ) : ranks?.daily_book ? (
            <p className="text-[10px] text-qa-muted">
              Разбор книги появится, когда накопится несколько закрытых дней.
            </p>
          ) : null}
        </div>
      </AppPageShell>
  );
}

export default function ForecastingPage() {
  return (
    <div className="min-h-screen bg-cockpit-bg text-qa-text flex flex-col operator-shell">
      <NavBar activeTab="forecasting" />
      <PageErrorBoundary title="Прогноз и Risk Engine">
        <ForecastingPageContent />
      </PageErrorBoundary>
    </div>
  );
}
