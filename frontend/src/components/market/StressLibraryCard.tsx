"use client";

import { useQuery } from "@tanstack/react-query";
import { forecastApi } from "@/lib/api";
import { useProductContext } from "@/contexts/ProductContext";
import { queryKeys } from "@/lib/queryKeys";

export function StressLibraryCard() {
  const { activeAccount, mode } = useProductContext();
  const { data, isLoading, isError } = useQuery({
    queryKey: queryKeys.stress(activeAccount, mode),
    queryFn: () => forecastApi.stress(activeAccount, mode),
  });
  if (isLoading) return <p className="text-xs text-qa-muted">Стресс: загрузка…</p>;
  if (isError) return <p className="text-xs text-qa-muted">Стресс: нет данных</p>;
  if (!data) return null;
  if (data.empty || !Array.isArray(data.scenarios) || data.scenarios.length === 0) {
    return (
      <div className="cockpit-panel p-4">
        <p className="text-[10px] uppercase tracking-wide text-qa-muted">Стресс-библиотека</p>
        <p className="text-sm mt-1">Нет позиций в книге — сценарии не к чему применить.</p>
        <p className="text-xs text-qa-muted mt-1">{data.disclaimer}</p>
      </div>
    );
  }
  const worst = [...data.scenarios].sort((a, b) => a.pnl_pct - b.pnl_pct)[0];
  return (
    <div className="cockpit-panel p-4">
      <p className="text-[10px] uppercase tracking-wide text-qa-muted">Стресс-библиотека</p>
      <p className="text-sm mt-1">
        Худший сценарий: {worst.title} · {(worst.pnl_pct * 100).toFixed(1)}%
        {worst.limited_accuracy ? " · ограниченная точность" : ""}
      </p>
    </div>
  );
}
