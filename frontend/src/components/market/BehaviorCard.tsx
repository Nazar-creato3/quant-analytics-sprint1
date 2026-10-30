"use client";

import { useQuery } from "@tanstack/react-query";
import { forecastApi } from "@/lib/api";
import { useProductContext } from "@/contexts/ProductContext";
import { queryKeys } from "@/lib/queryKeys";

export function BehaviorCard() {
  const { activeAccount, mode } = useProductContext();
  const { data, isLoading, isError } = useQuery({
    queryKey: queryKeys.behavior(activeAccount, mode),
    queryFn: () => forecastApi.behavior(activeAccount, mode),
  });
  if (isLoading) return <p className="text-xs text-qa-muted">Поведение: загрузка…</p>;
  if (isError) return <p className="text-xs text-qa-muted">Поведение: нет данных</p>;
  if (!data) return null;
  return (
    <div className="cockpit-panel p-4">
      <p className="text-[10px] uppercase tracking-wide text-qa-muted">Поведенческие сигналы</p>
      <p className="text-sm mt-1">{data.text}</p>
      <p className="text-xs text-qa-muted mt-1">Выборка: {data.sample_size} закрытий</p>
    </div>
  );
}
