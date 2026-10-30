"use client";

import { useEffect, useRef } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { format, parseISO } from "date-fns";
import { clsx } from "clsx";
import { NEWS_DISPLAY_COUNT } from "@/constants/news";
import { newsApi } from "@/lib/api";
import { NewsArticle } from "@/types";
import { CockpitPanelHeader } from "./CockpitPanelHeader";
import { ReasonState } from "./ReasonState";
import {
  displayNewsSummary,
  displayNewsTitle,
} from "@/components/news/newsDisplay";
import { CrossActions } from "@/components/shared/CrossActions";

const SENTIMENT_RU: Record<string, string> = {
  positive: "позитив",
  negative: "негатив",
  neutral: "нейтрально",
};

function sentimentBadge(label: string | null | undefined): string {
  if (label === "positive") return "text-terminal-up bg-qa-success-bg border-terminal-up/40";
  if (label === "negative") return "text-terminal-down bg-qa-danger-bg border-terminal-down/40";
  return "text-qa-muted bg-qa-panel-secondary/60 border-qa-border-strong/60";
}

interface NewsPanelProps {
  compact?: boolean;
  maxItems?: number;
  enabled?: boolean;
  className?: string;
}

export function NewsPanel({
  compact = false,
  maxItems = NEWS_DISPLAY_COUNT,
  enabled = true,
  className,
}: NewsPanelProps) {
  const queryClient = useQueryClient();
  const fetchAttempted = useRef(false);

  const { data, isLoading, error } = useQuery({
    queryKey: ["economic-news", maxItems],
    queryFn: () => newsApi.list({ page: 1, page_size: maxItems }),
    staleTime: 120_000,
    refetchInterval: 120_000,
    enabled,
  });

  const fetchMutation = useMutation({
    mutationFn: () => newsApi.fetch(),
    onSuccess: () => {
      setTimeout(() => {
        queryClient.invalidateQueries({ queryKey: ["economic-news"] });
      }, 5000);
    },
  });

  const apiItems = (data?.items ?? []) as NewsArticle[];
  const items = apiItems.slice(0, maxItems);

  useEffect(() => {
    if (!enabled || isLoading || fetchAttempted.current) return;
    if (apiItems.length === 0 && !error) {
      fetchAttempted.current = true;
      fetchMutation.mutate();
    }
  }, [enabled, isLoading, apiItems.length, error, fetchMutation]);

  return (
    <div
      className={clsx(
        "cockpit-panel flex flex-col overflow-hidden",
        compact ? "shrink-0 max-h-36" : "flex-1 min-h-0",
        className,
      )}
    >
      <CockpitPanelHeader
        title="Экономические новости"
        badge={items.length}
        href="/operator/news"
      />

      <div className={clsx("flex-1 overflow-y-auto p-2", compact ? "space-y-1" : "space-y-1.5")}>
        {isLoading ? (
          <ReasonState code="loading" title="Загрузка новостей…" compact={compact} />
        ) : error ? (
          <ReasonState
            code="error"
            title="Не удалось загрузить новости"
            detail="Проверьте news ingestion и RSS-источники"
            compact={compact}
          />
        ) : items.length === 0 ? (
          <ReasonState
            code="no-data"
            title="Нет новостей"
            detail="Запустите news ingestion или дождитесь RSS-обновления (investing.com, RBC, Interfax)"
            compact={compact}
          />
        ) : (
          <>
            {items.map(article => {
              const ticker = (article.tickers_mentioned || [])[0];
              return (
              <div
                key={article.id}
                data-testid="news-cycle-item"
                className={clsx(
                  "cockpit-feed-item",
                  !compact && "px-3 py-2",
                )}
              >
                <a
                href={article.url}
                target="_blank"
                rel="noopener noreferrer"
                className="block"
              >
                <div className="flex items-start justify-between gap-2">
                  <p
                    className={clsx(
                      "text-qa-text leading-snug",
                      compact ? "text-xs line-clamp-2" : "text-sm line-clamp-2",
                    )}
                  >
                    {displayNewsTitle(article)}
                  </p>
                  <div className="flex flex-col items-end gap-1 shrink-0">
                    {article.sentiment_label && (
                      <span
                        className={clsx(
                          "text-[9px] uppercase px-1.5 py-0.5 rounded border font-medium",
                          sentimentBadge(article.sentiment_label),
                        )}
                      >
                        {SENTIMENT_RU[article.sentiment_label] ?? article.sentiment_label}
                      </span>
                    )}
                  </div>
                </div>
                {displayNewsSummary(article) && !compact && (
                  <p className="text-[11px] text-qa-muted mt-1 line-clamp-2 leading-snug">
                    {displayNewsSummary(article)}
                  </p>
                )}
                <div
                  className={clsx(
                    "flex items-center gap-2 mt-1.5 text-qa-muted",
                    compact ? "text-[10px]" : "text-[11px]",
                  )}
                >
                  <span className="font-medium text-qa-muted">{article.source}</span>
                  <span className="text-qa-muted">·</span>
                  <span className="tabular-nums">
                    {format(parseISO(article.published_at), "HH:mm · dd MMM")}
                  </span>
                </div>
              </a>
              {ticker ? <div className="mt-1"><CrossActions ticker={ticker} variant="menu" /></div> : null}
              </div>
              );
            })}
          </>
        )}
      </div>
    </div>
  );
}
