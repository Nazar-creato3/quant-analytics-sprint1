"use client";

import { useEffect, useState } from "react";
import { lane2Get } from "@/lib/lane2-fetch";
import { experimentLines } from "@/lib/experiments";

export function ExperimentStatusCard() {
  const [lines, setLines] = useState(experimentLines());
  useEffect(() => {
    void lane2Get("/experiments/status").then((row) => {
      const missing = "нет данных";
      setLines([
        "Эксперименты",
        `Решение основателя: ${String(row.decision ?? missing)}`,
        String(row.running) === "true" ? "Эксперимент запущен" : "Эксперимент не запущен",
        `Победитель: ${String(row.winner ?? missing)}`,
        `Размер выборки: ${String(row.sample_size ?? missing)}`,
      ]);
    });
  }, []);
  return (
    <section aria-labelledby="experiments-title" className="bg-white p-4 text-neutral-800">
      <h1 id="experiments-title" className="text-lg font-medium">
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
