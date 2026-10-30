"use client";

import { useQuery } from "@tanstack/react-query";
import { newsApi } from "@/lib/api";
import { newsMentionsTicker } from "@/lib/ticker-text-match";
import { fmtMskDateTime, relativeTime } from "../TermPanel";
import type { TerminalNewsItem } from "@/types/terminal";

export function TerminalTickerNews({
  symbol,
  snapshotNews,
}: {
  symbol: string;
  snapshotNews: TerminalNewsItem[];
}) {
  const { data } = useQuery({
    queryKey: ["economic-news", symbol, 12],
    queryFn: () => newsApi.list({ ticker: symbol, page: 1, page_size: 12 }),
    staleTime: 60_000,
    enabled: !!symbol,
  });

  const fromApi = (data?.items ?? []).map((n) => ({
      id: n.id,
      headline: n.title,
      source: n.source ?? "news",
      published_at: n.published_at,
      url: n.url,
    }));

  const fromSnap = snapshotNews.filter((n) =>
    newsMentionsTicker({ headline: n.headline, summary: n.summary }, symbol),
  );

  const seen = new Set<string>();
  const merged = [...fromApi, ...fromSnap].filter((n) => {
    const key = n.id || n.headline;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });

  return (
    <div>
      {merged.map((n) => (
        <div key={n.id} className="term-row !block space-y-0.5 !py-1">
          {n.url ? (
            <a
              href={n.url}
              target="_blank"
              rel="noreferrer"
              className="text-[10px] text-terminal-text hover:text-terminal-accent leading-snug block"
            >
              {n.headline}
            </a>
          ) : (
            <p className="text-[10px] text-terminal-text leading-snug">{n.headline}</p>
          )}
          <p className="text-[8px] text-terminal-muted">
            {n.source} · {fmtMskDateTime(n.published_at)} MSK · {relativeTime(n.published_at)} ago
          </p>
        </div>
      ))}
      {merged.length === 0 && (
        <p className="p-2 text-[10px] text-terminal-muted">Нет заголовков по {symbol}</p>
      )}
    </div>
  );
}
