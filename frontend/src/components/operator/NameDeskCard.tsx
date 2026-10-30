"use client";

import { useQuery } from "@tanstack/react-query";
import { clsx } from "clsx";
import { BookOpen, X } from "lucide-react";
import { marketApi } from "@/lib/api";

export function NameDeskCard({
  ticker,
  direction,
  open = true,
  onClose,
  variant = "overlay",
}: {
  ticker: string;
  direction?: string | null;
  /** Overlay mode: toggle visibility. Panel mode defaults to always open. */
  open?: boolean;
  onClose?: () => void;
  /** `overlay` floats over the chart; `panel` is a normal in-flow card. */
  variant?: "overlay" | "panel";
}) {
  const visible = variant === "panel" ? true : open;
  const { data, isLoading } = useQuery({
    queryKey: ["name-card", ticker, direction ?? ""],
    queryFn: () => marketApi.getNameCard(ticker, direction ?? undefined),
    enabled: !!ticker && visible,
    staleTime: 60_000,
  });

  if (!ticker || !visible) return null;

  const quote = (data?.quote as Record<string, unknown> | undefined) ?? {};
  const news = (Array.isArray(data?.news) ? data?.news : []) as Array<Record<string, unknown>>;
  const filings = (Array.isArray(data?.filings) ? data?.filings : []) as Array<Record<string, unknown>>;
  const shorts = (data?.shorts as Record<string, unknown> | undefined) ?? {};
  const whyPoints = Array.isArray(data?.why_points) ? (data.why_points as string[]) : [];
  const business = (data?.business as Record<string, unknown> | undefined) ?? {};
  const price = typeof quote.price === "number" ? quote.price : null;
  const chg = typeof quote.change_pct === "number" ? quote.change_pct : null;
  const metric = (key: string, digits = 2) => {
    const v = business[key];
    return typeof v === "number" && Number.isFinite(v) ? v.toFixed(digits) : null;
  };

  return (
    <div
      className={clsx(
        "overflow-y-auto bg-cockpit-panel",
        variant === "overlay"
          ? "absolute inset-x-0 bottom-0 z-20 max-h-[70%] border-t border-cockpit-border shadow-[0_-8px_24px_rgba(0,0,0,0.45)]"
          : "relative max-h-none",
      )}
    >
      <div className="sticky top-0 flex items-center justify-between gap-2 px-3 py-2 bg-cockpit-panel border-b border-cockpit-border">
        <div className="flex items-center gap-1.5 text-[10px] uppercase tracking-wide text-qa-muted">
          <BookOpen size={12} className="text-terminal-accent" />
          Выписка · {ticker}
        </div>
        {onClose ? (
          <button
            type="button"
            onClick={onClose}
            className="p-1 rounded text-qa-muted hover:text-qa-text"
            title="Закрыть выписку"
            aria-label="Закрыть выписку"
          >
            <X size={14} />
          </button>
        ) : null}
      </div>
      <div className="px-3 py-3 text-xs text-qa-text/90 space-y-3">
        {isLoading ? (
          <p className="text-qa-muted">Собираем цену, отчётность, короткие позиции и новости…</p>
        ) : (
          <>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              <section>
                <div className="text-qa-muted mb-1">Цена</div>
                <div className="tabular-nums font-semibold">
                  {price != null ? price.toFixed(2) : "—"}
                  {chg != null ? ` (${chg >= 0 ? "+" : ""}${chg.toFixed(2)}% за день)` : ""}
                </div>
                <p className="mt-1 leading-relaxed">{typeof data?.trend === "string" ? data.trend : "—"}</p>
                {typeof data?.vs_market === "string" ? (
                  <p className="mt-1 leading-relaxed">{data.vs_market}</p>
                ) : null}
              </section>
              <section>
                <div className="text-qa-muted mb-1">Бизнес</div>
                <p className="leading-relaxed">
                  {typeof data?.business_read === "string" ? data.business_read : "—"}
                </p>
                {typeof data?.filings_read === "string" ? (
                  <p className="mt-1 text-qa-muted">{data.filings_read}</p>
                ) : filings[0] ? (
                  <p className="mt-1 text-qa-muted">последний документ: {String(filings[0].form_type)}</p>
                ) : null}
                <div className="mt-2 grid grid-cols-2 gap-x-3 gap-y-1 tabular-nums text-[10px] text-qa-muted">
                  {metric("roe", 3) ? <span>отдача на капитал {metric("roe", 3)}</span> : null}
                  {metric("profit_margin", 3) ? <span>маржа {metric("profit_margin", 3)}</span> : null}
                  {metric("revenue", 0) ? <span>выручка {metric("revenue", 0)}</span> : null}
                  {metric("net_income", 0) ? <span>прибыль {metric("net_income", 0)}</span> : null}
                </div>
              </section>
              <section>
                <div className="text-qa-muted mb-1">Короткие позиции</div>
                <p className="leading-relaxed">{typeof shorts.read === "string" ? shorts.read : "—"}</p>
              </section>
              <section>
                <div className="text-qa-muted mb-1">Новости</div>
                {news.length ? (
                  <ul className="space-y-1.5">
                    {news.slice(0, 5).map((n, i) => (
                      <li key={`${String(n.url || n.title || i)}`}>
                        <a
                          href={String(n.url || "#")}
                          target="_blank"
                          rel="noreferrer"
                          className="block text-primary leading-relaxed"
                        >
                          {String(n.title || "")}
                        </a>
                        {n.source ? (
                          <span className="text-[10px] text-qa-muted">{String(n.source)}</span>
                        ) : null}
                        {n.summary ? (
                          <p className="text-[10px] text-qa-muted mt-0.5 leading-snug">
                            {String(n.summary).slice(0, 180)}
                          </p>
                        ) : null}
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="text-qa-muted">
                    {typeof data?.news_read === "string" ? data.news_read : "свежих заголовков пока нет"}
                  </p>
                )}
              </section>
            </div>
            <section>
              <div className="text-qa-muted mb-1">Почему так смотрим сегодня</div>
              {whyPoints.length ? (
                <ul className="list-disc pl-4 space-y-1 leading-relaxed">
                  {whyPoints.map((point) => (
                    <li key={point}>{point}</li>
                  ))}
                </ul>
              ) : (
                <p className="leading-relaxed">
                  {typeof data?.why === "string" ? data.why : "собираем объяснение"}
                </p>
              )}
            </section>
          </>
        )}
      </div>
    </div>
  );
}

export function NameDeskToggle({
  open,
  onToggle,
}: {
  open: boolean;
  onToggle: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onToggle}
      className={`p-1 rounded border ${
        open
          ? "border-terminal-accent/50 text-terminal-accent"
          : "border-qa-border text-qa-muted hover:text-qa-text"
      }`}
      title={open ? "Скрыть выписку по бумаге" : "Выписка по бумаге"}
      aria-label={open ? "Скрыть выписку" : "Открыть выписку"}
      aria-pressed={open}
    >
      <BookOpen size={12} />
    </button>
  );
}
