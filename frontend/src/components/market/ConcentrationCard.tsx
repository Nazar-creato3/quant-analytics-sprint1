"use client";

import { useQuery } from "@tanstack/react-query";
import { forecastApi } from "@/lib/api";
import { useProductContext } from "@/contexts/ProductContext";
import { queryKeys } from "@/lib/queryKeys";

export function ConcentrationCard() {
  const { activeAccount, mode } = useProductContext();
  const { data, isLoading, isError } = useQuery({
    queryKey: queryKeys.concentration(activeAccount, mode),
    queryFn: () => forecastApi.concentration(activeAccount, mode),
  });
  if (isLoading) return <p className="text-xs text-qa-muted">Концентрация: загрузка…</p>;
  if (isError) return <p className="text-xs text-qa-muted">Концентрация: нет данных</p>;
  if (!data) return null;
  if (data.empty) {
    return (
      <div className="cockpit-panel p-4">
        <p className="text-[10px] uppercase tracking-wide text-qa-muted">Концентрация</p>
        <p className="text-sm mt-1">Нет позиций — доли не считаются.</p>
      </div>
    );
  }
  return (
    <div className="cockpit-panel p-4">
      <p className="text-[10px] uppercase tracking-wide text-qa-muted">Концентрация</p>
      <p className="text-sm mt-1">HHI {data.hhi} · эффективных ставок {data.effective_bets}</p>
    </div>
  );
}
