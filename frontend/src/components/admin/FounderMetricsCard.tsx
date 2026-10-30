"use client";

import { useEffect, useState } from "react";
import { lane2Get } from "@/lib/lane2-fetch";
import { founderLines } from "@/lib/founder-metrics";

export function FounderMetricsCard() {
  const [lines, setLines] = useState(founderLines());
  useEffect(() => {
    void Promise.all([lane2Get("/analytics/metrics"), lane2Get("/support/status")]).then(([metrics, support]) => {
      const missing = "нет данных";
      const frequent = support.frequent;
      const frequentText =
        frequent && typeof frequent === "object" && !Array.isArray(frequent)
          ? JSON.stringify(frequent)
          : String(frequent ?? missing);
      setLines([
        "Метрики основателя",
        `Активация: ${String(metrics.activation ?? missing)}`,
        `Удержание: ${String(metrics.retention ?? missing)}`,
        `Воронка манёвров: ${String(metrics.funnel ?? missing)}`,
        `Доля анкет: ${String(metrics.profile_share ?? missing)}`,
        `Время до первого отчёта: ${String(metrics.time_to_report ?? missing)}`,
        `Ошибки подключения: ${String(metrics.connect_errors ?? missing)}`,
        `Сводка Slack: ${missing}`,
        `Частые проблемы: ${frequentText}`,
        `Цель главной метрики: ${missing}`,
      ]);
    });
  }, []);
  return (
    <section aria-labelledby="founder-metrics-title" className="bg-white p-4 text-neutral-800">
      <h1 id="founder-metrics-title" className="text-lg font-medium">
        {lines[0]}
      </h1>
      <ul className="mt-2 list-disc pl-5 text-sm text-neutral-700">
        {lines.slice(1).map((line) => (
          <li key={line}>{line}</li>
        ))}
      </ul>
    </section>
  );
}
