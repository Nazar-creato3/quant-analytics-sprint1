"use client";

import { useQuery } from "@tanstack/react-query";
import { forecastApi } from "@/lib/api";
import { NavBar } from "@/components/layout/NavBar";
import { AppPageShell } from "@/components/layout/AppPageShell";

export default function ForecastAccuracyPage() {
  const { data, isLoading, error } = useQuery({
    queryKey: ["forecast-accuracy"],
    queryFn: () => forecastApi.accuracy(),
  });
  const { data: risk } = useQuery({
    queryKey: ["model-risk"],
    queryFn: () => forecastApi.modelRisk(),
  });
  return (
    <div className="min-h-screen bg-cockpit-bg text-qa-text flex flex-col">
      <NavBar />
      <AppPageShell title="Точность прогнозов">
        {isLoading ? <p className="text-qa-muted">Загрузка…</p> : null}
        {error ? <p className="text-terminal-down">Не удалось загрузить журнал</p> : null}
        {data ? (
          <div className="space-y-3">
            <p className="text-sm text-qa-muted">{data.methodology}</p>
            {risk ? (
              <p className="text-sm">
                {risk.validation?.brier == null
                  ? "нет данных"
                  : `Статус: ${risk.validation.status}. ${risk.user_reason}`}
              </p>
            ) : null}
            {!data.horizons?.length ? (
              <p className="text-sm">Пока нет зафиксированных горизонтов в журнале.</p>
            ) : (
              <ul className="text-sm space-y-1">
                {data.horizons.map((h) => (
                  <li key={h.horizon_days}>
                    {h.horizon_days} дн.: точность {(h.accuracy * 100).toFixed(1)}%
                    {h.beats_naive ? " — лучше простого ориентира" : " — не лучше простого ориентира"}
                  </li>
                ))}
              </ul>
            )}
          </div>
        ) : null}
      </AppPageShell>
    </div>
  );
}
