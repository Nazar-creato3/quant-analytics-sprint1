"use client";

import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { forecastApi } from "@/lib/api";
import { DataState } from "@/components/shared/DataState";

export function LimitsDigestPanel() {
  const [userId, setUserId] = useState("demo");
  const limitsQ = useQuery({
    queryKey: ["personal-limits", userId],
    queryFn: () => forecastApi.personalLimits(userId),
    retry: false,
  });
  const calQ = useQuery({
    queryKey: ["instrument-calendar", userId],
    queryFn: () => forecastApi.instrumentCalendar(userId),
    retry: false,
  });
  const digestQ = useQuery({
    queryKey: ["digest", userId],
    queryFn: () => forecastApi.digestPreview(userId),
    retry: false,
  });
  const put = useMutation({
    mutationFn: () => forecastApi.putPersonalLimits({ user_id: userId, concentration: 0.3, drawdown: 0.2 }),
  });

  const flagOff = limitsQ.isError && calQ.isError && digestQ.isError;

  return (
    <section className="rounded-xl border border-qa-border bg-qa-card p-4 space-y-2">
      <h2 className="text-sm font-semibold text-qa-text">Лимиты, календарь, регулярный отчёт</h2>
      <p className="text-xs text-qa-muted">Пока выключено: письма не отправляются.</p>
      {flagOff ? <p className="text-xs text-qa-muted">Функция ещё не включена.</p> : null}
      <label className="block text-xs text-qa-muted">
        Учёт
        <input className="mt-1 w-full rounded border border-qa-border bg-transparent px-2 py-1" value={userId} onChange={(e) => setUserId(e.target.value)} />
      </label>
      <DataState loading={limitsQ.isLoading} error={limitsQ.isError} empty={limitsQ.data?.data_status === "нет данных"}>
        <p className="text-xs">Лимиты: {limitsQ.data?.data_status || "нет данных"}</p>
      </DataState>
      <p className="text-xs">Календарь: {calQ.data?.data_status || "нет данных"}</p>
      <p className="text-xs">Дайджест доставка: {digestQ.data?.delivery ? "вкл" : "выкл"}</p>
      <button type="button" className="text-xs underline text-qa-muted" onClick={() => put.mutate()}>
        Сохранить черновик лимитов
      </button>
    </section>
  );
}
