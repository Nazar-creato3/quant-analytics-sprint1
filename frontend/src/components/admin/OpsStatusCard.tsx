"use client";

import { useEffect, useState } from "react";
import { backupOpsLines } from "@/lib/backup-ops";
import {
  fetchOpsObserve,
  fetchOpsPerf,
  OPS_DRILLS,
  opsLines,
  runOpsDrill,
  runOpsPerf,
  type OpsObserveView,
  type OpsPerfView,
} from "@/lib/ops-observe";

function isError(view: unknown): view is { error: string } {
  return Boolean(view && typeof view === "object" && "error" in view);
}

export function OpsStatusCard() {
  const lines = opsLines();
  const backup = backupOpsLines();
  const [view, setView] = useState<OpsObserveView | { error: string } | null>(null);
  const [perf, setPerf] = useState<OpsPerfView | { error: string } | null>(null);
  const [drillMsg, setDrillMsg] = useState<string>("");
  const [busy, setBusy] = useState(false);

  const reload = async () => {
    const [nextObserve, nextPerf] = await Promise.all([fetchOpsObserve(), fetchOpsPerf()]);
    setView(nextObserve);
    setPerf(nextPerf);
  };

  useEffect(() => {
    let cancelled = false;
    reload().then(() => {
      if (cancelled) return;
    });
    return () => {
      cancelled = true;
    };
  }, []);

  const loading = view === null;
  const failed = view !== null && isError(view);
  const otel =
    view && !isError(view) && view.otel?.sdk === "on"
      ? `OpenTelemetry: ${view.otel.exporter ?? "in_memory"}`
      : null;
  const slo = view && !isError(view) ? view.slo : undefined;
  const alerts =
    view && !isError(view) && Array.isArray(view.alerts) ? view.alerts : [];

  const onDrill = async (name: string) => {
    setBusy(true);
    setDrillMsg("");
    const result = await runOpsDrill(name);
    setBusy(false);
    if (isError(result)) {
      setDrillMsg("нет данных");
      return;
    }
    setDrillMsg(`${String(result.runbook)} → ${String(result.alert)}`);
    await reload();
  };

  const onPerfRun = async () => {
    setBusy(true);
    const result = await runOpsPerf();
    setBusy(false);
    setPerf(result);
  };

  return (
    <div className="space-y-4 text-sm">
      <section aria-labelledby="ops-observe-title" className="rounded-xl border border-qa-border p-3">
        <h2 id="ops-observe-title" className="font-medium">
          {lines[0]}
        </h2>
        {loading ? <p className="mt-1 text-xs text-qa-muted">Загрузка</p> : null}
        {failed ? <p className="mt-1 text-xs text-qa-muted">нет данных</p> : null}
        <p className="mt-1 text-xs text-qa-muted">{lines[1]}</p>
        <p className="mt-1 text-xs text-qa-muted">{lines[2]}</p>
        <p className="mt-1 text-xs text-qa-muted">{lines[3]}</p>
        {otel ? <p className="mt-1 text-xs text-qa-muted">{otel}</p> : null}
      </section>

      <section aria-labelledby="ops-slo-title" className="rounded-xl border border-qa-border p-3">
        <h2 id="ops-slo-title" className="font-medium">
          SLO
        </h2>
        <p className="mt-1 text-xs text-qa-muted">API: {slo?.api ?? "нет данных"}</p>
        <p className="mt-1 text-xs text-qa-muted">
          API p95 мс: {slo?.api_p95_ms ?? "нет данных"}
        </p>
        <p className="mt-1 text-xs text-qa-muted">Отчёт: {slo?.report ?? "нет данных"}</p>
        <p className="mt-1 text-xs text-qa-muted">
          Синхронизация: {slo?.sync_timeout_seconds ?? "нет данных"}
        </p>
        <p className="mt-1 text-xs text-qa-muted">
          Доступность: {slo?.availability ?? "нет данных"}
        </p>
        <p className="mt-1 text-xs text-qa-muted">
          Алерты: {alerts.length ? alerts.join(", ") : "нет данных"}
        </p>
      </section>

      <section aria-labelledby="ops-drills-title" className="rounded-xl border border-qa-border p-3">
        <h2 id="ops-drills-title" className="font-medium">
          Drills
        </h2>
        <div className="mt-2 flex flex-wrap gap-2">
          {OPS_DRILLS.map((name) => (
            <button
              key={name}
              type="button"
              disabled={busy}
              className="rounded border border-qa-border px-2 py-1 text-xs disabled:opacity-50"
              onClick={() => onDrill(name)}
            >
              {name}
            </button>
          ))}
        </div>
        {drillMsg ? <p className="mt-2 text-xs text-qa-muted">{drillMsg}</p> : null}
      </section>

      <section aria-labelledby="ops-perf-title" className="rounded-xl border border-qa-border p-3">
        <h2 id="ops-perf-title" className="font-medium">
          Perf
        </h2>
        {perf === null ? <p className="mt-1 text-xs text-qa-muted">Загрузка</p> : null}
        {perf && isError(perf) ? (
          <p className="mt-1 text-xs text-qa-muted">нет данных</p>
        ) : null}
        {perf && !isError(perf) ? (
          <>
            <p className="mt-1 text-xs text-qa-muted">Статус: {perf.status ?? "нет данных"}</p>
            <p className="mt-1 text-xs text-qa-muted">
              Checksum: {perf.checksum ?? "нет данных"}
            </p>
            <p className="mt-1 text-xs text-qa-muted">
              elapsed_ms: {perf.elapsed_ms ?? "нет данных"}
            </p>
            <p className="mt-1 text-xs text-qa-muted">
              users_executed: {perf.users_executed ?? "нет данных"}
            </p>
            <p className="mt-1 text-xs text-qa-muted">
              database_profile: {perf.database_profile ?? "нет данных"}
            </p>
          </>
        ) : null}
        <button
          type="button"
          disabled={busy}
          className="mt-2 rounded border border-qa-border px-2 py-1 text-xs disabled:opacity-50"
          onClick={() => onPerfRun()}
        >
          Запустить бюджет
        </button>
      </section>

      <section aria-labelledby="backup-ops-title" className="rounded-xl border border-qa-border p-3">
        <h2 id="backup-ops-title" className="font-medium">
          {backup[0]}
        </h2>
        <p className="mt-1 text-xs text-qa-muted">{backup[1]}</p>
        <p className="mt-1 text-xs text-qa-muted">{backup[2]}</p>
        <p className="mt-1 text-xs text-qa-muted">{backup[3]}</p>
      </section>
    </div>
  );
}
