"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { AlertTriangle, BarChart3, ShieldCheck } from "lucide-react";

type LevelAccuracy = {
  level: string;
  accuracy: number;
  total_points: number;
  notes?: string;
};

type RegimeAccuracy = {
  regime: string;
  accuracy: number;
  sample_size: number;
  confidence_note: string;
};

type TrackRecordPayload = {
  generated_at: string;
  period_days: number;
  benchmark_count: number;
  total_validation_points: number;
  aggregate_calibration_error: number;
  aggregate_brier_score: number;
  level_accuracy: LevelAccuracy[];
  regime_accuracy: RegimeAccuracy[];
  low_confidence_regimes: string[];
  summary: string;
  disclaimer: string;
};

function pct(value: number): string {
  return `${(value * 100).toFixed(1)}%`;
}

export default function TrackRecordPage() {
  const [data, setData] = useState<TrackRecordPayload | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const base =
          process.env.NEXT_PUBLIC_API_URL?.replace(/\/$/, "") ||
          (typeof window !== "undefined" &&
          (window.location.hostname === "localhost" ||
            window.location.hostname === "127.0.0.1")
            ? "http://localhost:8000"
            : "");
        const response = await fetch(`${base}/api/v1/track-record/public`);
        if (!response.ok) {
          throw new Error("Не удалось загрузить данные");
        }
        const payload = (await response.json()) as TrackRecordPayload;
        if (!cancelled) setData(payload);
      } catch (err) {
        if (!cancelled) {
          setError("Не удалось загрузить данные");
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <div className="min-h-screen bg-cockpit-bg text-qa-text">
      <div className="mx-auto max-w-4xl px-4 py-10 space-y-8">
        <header className="space-y-3">
          <div className="flex items-center gap-2 text-terminal-accent text-sm font-medium">
            <BarChart3 className="h-4 w-4" />
            Публичный track record
          </div>
          <h1 className="text-3xl font-semibold tracking-tight">
            Анонимизированная статистика точности
          </h1>
          <p className="text-sm text-qa-muted max-w-2xl">
            Агрегированные метрики валидации прогнозной иерархии по эталонным
            рядам. Без данных конкретных клиентов или персональных идентификаторов.
          </p>
          <Link href="/login" className="text-sm text-primary hover:text-accent">
            ← Войти в платформу
          </Link>
        </header>

        {error && (
          <div className="rounded-lg border border-rose-900/50 bg-rose-950/30 px-4 py-3 text-sm text-rose-200">
            {error}
          </div>
        )}

        {data && (
          <>
            <section className="grid gap-4 sm:grid-cols-3">
              <MetricCard label="Точек валидации" value={String(data.total_validation_points)} />
              <MetricCard label="Калибровка (avg)" value={data.aggregate_calibration_error.toFixed(3)} />
              <MetricCard label="Brier (avg)" value={data.aggregate_brier_score.toFixed(3)} />
            </section>

            <section className="rounded-xl border border-cockpit-border bg-cockpit-panel p-5 space-y-3">
              <div className="flex items-center gap-2 text-terminal-up text-sm">
                <ShieldCheck className="h-4 w-4" />
                Сводка
              </div>
              <p className="text-sm text-qa-text">{data.summary}</p>
              <p className="text-xs text-qa-muted">
                Обновлено: {new Date(data.generated_at).toLocaleString("ru-RU")} ·
                период {data.period_days} дн. · {data.benchmark_count} эталонных рядов
              </p>
            </section>

            {data.low_confidence_regimes.length > 0 && (
              <section className="rounded-xl alert-caution-panel p-4 flex gap-3">
                <AlertTriangle className="h-5 w-5 text-terminal-accent shrink-0 mt-0.5" />
                <div className="text-sm text-qa-text">
                  <p className="font-medium mb-1">Режимы с пониженной уверенностью</p>
                  <p>{data.low_confidence_regimes.join(", ")}</p>
                </div>
              </section>
            )}

            <section className="rounded-xl border border-cockpit-border bg-cockpit-panel p-5">
              <h2 className="text-lg font-medium mb-4">Точность по уровням иерархии</h2>
              <div className="overflow-x-auto">
                <table className="min-w-full text-sm">
                  <thead>
                    <tr className="text-left text-qa-muted border-b border-cockpit-border">
                      <th className="py-2 pr-4">Уровень</th>
                      <th className="py-2 pr-4">Точность</th>
                      <th className="py-2">Точек</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.level_accuracy.map((row) => (
                      <tr key={row.level} className="border-b border-cockpit-border/60">
                        <td className="py-2 pr-4 font-mono text-xs">{row.level}</td>
                        <td className="py-2 pr-4">{pct(row.accuracy)}</td>
                        <td className="py-2">{row.total_points}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>

            <section className="rounded-xl border border-cockpit-border bg-cockpit-panel p-5">
              <h2 className="text-lg font-medium mb-4">Точность по режимам</h2>
              <div className="space-y-3">
                {data.regime_accuracy.map((row) => (
                  <div
                    key={row.regime}
                    className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-1 border-b border-cockpit-border/40 pb-3"
                  >
                    <div>
                      <p className="font-mono text-sm">{row.regime}</p>
                      <p className="text-xs text-qa-muted">{row.confidence_note}</p>
                    </div>
                    <div className="text-sm">
                      {pct(row.accuracy)} · n={row.sample_size}
                    </div>
                  </div>
                ))}
              </div>
            </section>
          </>
        )}

        {!data && !error && (
          <p className="text-sm text-qa-muted">Загрузка публичной статистики…</p>
        )}
      </div>
    </div>
  );
}

function MetricCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl border border-cockpit-border bg-cockpit-panel p-4">
      <p className="text-xs text-qa-muted mb-1">{label}</p>
      <p className="text-2xl font-semibold tabular-nums">{value}</p>
    </div>
  );
}
