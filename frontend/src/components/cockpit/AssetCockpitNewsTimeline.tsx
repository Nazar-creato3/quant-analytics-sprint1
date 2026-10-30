"use client";

import { format, parseISO } from "date-fns";
import { ru } from "date-fns/locale";
import { clsx } from "clsx";
import { useQuery } from "@tanstack/react-query";
import type { NewsArticle } from "@/types";
import { newsApi } from "@/lib/api";
import { CockpitPanelHeader } from "@/components/operator/CockpitPanelHeader";
import { Spinner } from "@/components/ui";
import { useMemo } from "react";
import {
  displayNewsSummary,
  displayNewsTitle,
} from "@/components/news/newsDisplay";

/** Keep in sync with backend `_TICKER_ALIASES` (word-boundary safe). */
const TICKER_ALIASES: Record<string, string[]> = {
  QQQ: ["NASDAQ", "NASDAQ-100", "NDX", "INVESCO QQQ"],
  SPY: ["S&P 500", "S&P500", "SPX", "SP500"],
  IVV: ["S&P 500", "S&P500", "SPX"],
  AAPL: ["APPLE"],
  MSFT: ["MICROSOFT"],
  GOOGL: ["GOOGLE", "ALPHABET"],
  GOOG: ["GOOGLE", "ALPHABET"],
  AMZN: ["AMAZON"],
  META: ["FACEBOOK", "META PLATFORMS"],
  NVDA: ["NVIDIA"],
  TSLA: ["TESLA"],
  SBER: ["SBERBANK", "СБЕР"],
  GAZP: ["GAZPROM", "ГАЗПРОМ"],
  LKOH: ["LUKOIL", "ЛУКОЙЛ"],
  MOEX: ["MOSCOW EXCHANGE", "МОСКОВСКАЯ БИРЖА"],
};

function sentimentColor(article: NewsArticle): string {
  const label = article.sentiment_label?.toLowerCase();
  if (label === "positive" || (article.sentiment_score ?? 0) > 0.15) {
    return "border-l-terminal-up text-terminal-up/90";
  }
  if (label === "negative" || (article.sentiment_score ?? 0) < -0.15) {
    return "border-l-terminal-down text-terminal-down/90";
  }
  return "border-l-qa-border text-qa-muted";
}

function tokenInText(text: string, token: string): boolean {
  const t = token.trim().toUpperCase();
  if (!t) return false;
  const upper = text.toUpperCase();
  if (t.includes(" ")) return upper.includes(t);
  // Word-boundary: META must not match METALS
  const re = new RegExp(`(?<![A-Z0-9А-Я])${t.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}(?![A-Z0-9А-Я])`);
  return re.test(upper);
}

function articleMatchesTicker(article: NewsArticle, ticker: string): boolean {
  const t = ticker.trim().toUpperCase();
  const text = `${article.title ?? ""} ${article.description ?? ""}`;
  // Do not trust stale DB tags alone (META was wrongly tagged on METALS headlines).
  if (tokenInText(text, t) || tokenInText(text, `$${t}`)) return true;
  return (TICKER_ALIASES[t] ?? []).some((alias) => tokenInText(text, alias));
}

interface AssetCockpitNewsTimelineProps {
  symbol: string;
  articles: NewsArticle[];
  className?: string;
}

export function AssetCockpitNewsTimeline({
  symbol,
  articles,
  className,
}: AssetCockpitNewsTimelineProps) {
  const normalized = symbol.trim().toUpperCase();

  const filteredPropArticles = useMemo(
    () => articles.filter((a) => articleMatchesTicker(a, normalized)),
    [articles, normalized],
  );

  const { data: newsPage, isLoading } = useQuery({
    queryKey: ["cockpit-news", normalized],
    queryFn: () => newsApi.list({ ticker: normalized, page: 1, page_size: 12 }),
    staleTime: 60_000,
    enabled: !!normalized,
  });

  const displayArticles = useMemo(() => {
    const fromApi = (newsPage?.items ?? []).filter((article) =>
      articleMatchesTicker(article, normalized),
    );
    const byId = new Map<string, NewsArticle>();
    for (const a of [...filteredPropArticles, ...fromApi]) {
      byId.set(a.id, a);
    }
    return [...byId.values()].sort(
      (a, b) => new Date(b.published_at).getTime() - new Date(a.published_at).getTime(),
    );
  }, [filteredPropArticles, newsPage?.items, normalized]);

  return (
    <div className={clsx("cockpit-panel flex flex-col min-h-0", className)}>
      <CockpitPanelHeader title="News Timeline" subtitle={normalized} badge={displayArticles.length} />
      <div className="flex-1 overflow-y-auto p-2 space-y-1.5 min-h-0 max-h-72">
        {isLoading && displayArticles.length === 0 ? (
          <div className="flex justify-center py-6">
            <Spinner size={18} />
          </div>
        ) : displayArticles.length === 0 ? (
          <p className="text-xs text-qa-muted px-2 py-4">
            Нет тематических новостей по {normalized}. Обновите кокпит или дождитесь ingest.
          </p>
        ) : (
          displayArticles.map((article) => (
            <a
              key={article.id}
              href={article.url}
              target="_blank"
              rel="noopener noreferrer"
              className={clsx(
                "cockpit-feed-item block border-l-2 pl-2",
                sentimentColor(article),
              )}
            >
              <div className="flex items-start justify-between gap-2">
                <div className="text-[11px] text-qa-text leading-snug line-clamp-2 min-w-0">
                  {displayNewsTitle(article)}
                </div>
              </div>
              {displayNewsSummary(article) && (
                <p className="text-[10px] text-qa-muted mt-1 line-clamp-2 leading-snug">
                  {displayNewsSummary(article)}
                </p>
              )}
              <div className="flex items-center gap-2 mt-1 text-[10px] text-qa-muted">
                <span>{article.source}</span>
                <span>·</span>
                <span className="tabular-nums">
                  {format(parseISO(article.published_at), "dd MMM HH:mm", { locale: ru })}
                </span>
                {article.sentiment_score != null && (
                  <>
                    <span>·</span>
                    <span className="font-mono tabular-nums">
                      {article.sentiment_score > 0 ? "+" : ""}
                      {article.sentiment_score.toFixed(2)}
                    </span>
                  </>
                )}
              </div>
            </a>
          ))
        )}
      </div>
    </div>
  );
}
