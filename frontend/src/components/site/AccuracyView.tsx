"use client";

import { useEffect, useState } from "react";
import { lane2Get } from "@/lib/lane2-fetch";
import { accuracyPageLines } from "@/lib/public-accuracy";

export function AccuracyView() {
  const [lines, setLines] = useState(accuracyPageLines());
  useEffect(() => {
    void lane2Get("/public/accuracy").then((row) => {
      const accuracy = String(row.accuracy ?? "нет данных");
      const weak = String(row.weak_periods ?? "нет данных");
      const byInstrument = String(row.by_instrument ?? "нет данных");
      const digest = String(row.digest ?? "");
      setLines([
        "Точность прогнозов",
        `Опубликованная точность: ${accuracy}.`,
        "Пока журнал пуст, интервал и сравнение с наивной моделью не выводятся.",
        `Слабые периоды: ${weak}.`,
        `Сводка по инструментам: ${byInstrument}.`,
        "Число на странице берётся из журнала и здесь не задаётся.",
        `Проверка снимка: GET /api/v1/public/accuracy/verify?digest=${digest}`,
      ]);
    });
  }, []);
  return (
    <main className="mx-auto max-w-3xl bg-white p-4 text-neutral-800">
      <h1 className="text-lg font-medium">{lines[0]}</h1>
      {lines.slice(1).map((line) => (
        <p key={line} className="mt-2 text-sm text-neutral-700">
          {line}
        </p>
      ))}
    </main>
  );
}
