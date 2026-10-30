"use client";

import { useQuery } from "@tanstack/react-query";
import api from "@/lib/api";

export type FeedFreshnessState = {
  stale: boolean;
  ageMs: number;
  label: string;
};

type DataHealthResponse = {
  as_of?: string;
  quotes?: { symbol?: string; age_sec?: number; stale?: boolean }[];
  alerts?: { severity?: string; title?: string }[];
};

export function useFeedFreshness(_key?: string) {
  const q = useQuery({
    queryKey: ["terminal-data-health"],
    queryFn: async (): Promise<DataHealthResponse> => {
      const { data } = await api.get<DataHealthResponse>("/terminal/data-health", {
        params: { refresh: false },
      });
      return data;
    },
    staleTime: 30_000,
    refetchInterval: 60_000,
  });

  const quotes = q.data?.quotes ?? [];
  const maxAgeSec = quotes.reduce((m, row) => Math.max(m, row.age_sec ?? 0), 0);
  const stale = quotes.some((row) => row.stale) || maxAgeSec > 120;

  return {
    stale,
    ageMs: maxAgeSec * 1000,
    label: stale ? "устарели" : "свежие",
    isLoading: q.isLoading,
  } satisfies FeedFreshnessState & { isLoading: boolean };
}
