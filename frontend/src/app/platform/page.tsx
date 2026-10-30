"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { NavBar } from "@/components/layout/NavBar";
import { AppPageShell } from "@/components/layout/AppPageShell";
import { PageErrorBoundary } from "@/components/layout/PageErrorBoundary";
import { platformApi } from "@/lib/api";

function num(v: unknown): string {
  if (v == null || v === "") return "—";
  const n = Number(v);
  return Number.isFinite(n) ? n.toFixed(4) : String(v);
}

function PlatformDeskView() {
  const qc = useQueryClient();
  const [banned, setBanned] = useState("");
  const [esg, setEsg] = useState("");
  const [cap, setCap] = useState("250");
  const [risk, setRisk] = useState("2");

  const desk = useQuery({
    queryKey: ["platform-desk"],
    queryFn: () => platformApi.desk(false),
    staleTime: 30_000,
  });

  const ipsQ = useQuery({
    queryKey: ["platform-ips"],
    queryFn: platformApi.getIps,
    staleTime: 15_000,
  });

  const saveIps = useMutation({
    mutationFn: () =>
      platformApi.saveIps({
        deploy_cap: cap ? Number(cap) : null,
        max_risk_pct: Number(risk) || 2,
        banned_tickers: banned.split(/[,\s]+/).map((s) => s.trim()).filter(Boolean),
        esg_keywords: esg.split(/[,\s]+/).map((s) => s.trim()).filter(Boolean),
        max_name_frac: 0.1,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["platform-ips"] });
      qc.invalidateQueries({ queryKey: ["platform-desk"] });
    },
  });

  const report = (desk.data?.report || {}) as Record<string, any>;
  const tear = (report.tear || {}) as Record<string, unknown>;
  const brinson = (report.brinson || {}) as Record<string, unknown>;
  const rc = (report.risk_contribution || []) as Array<Record<string, unknown>>;
  const monitor = (desk.data?.monitor || {}) as Record<string, any>;
  const freshness = (monitor.freshness || []) as Array<Record<string, unknown>>;

  useEffect(() => {
    if (!ipsQ.data) return;
    setBanned((ipsQ.data.banned_tickers || []).join(", "));
    setEsg((ipsQ.data.esg_keywords || []).join(", "));
    if (ipsQ.data.deploy_cap != null) setCap(String(ipsQ.data.deploy_cap));
    if (ipsQ.data.max_risk_pct != null) setRisk(String(ipsQ.data.max_risk_pct));
  }, [ipsQ.data]);

  return (
    <div className="space-y-6">
      <p className="text-sm text-qa-muted">
        Правила книги, отчёт клиенту и контроль свежести данных. Цифры ниже — по бумажной книге,
        не по боевому счёту. Мандат здесь не поднимает операторский лимит.
      </p>

      <section className="cockpit-panel p-4 space-y-3">
        <h2 className="text-sm font-bold uppercase tracking-wide text-terminal-accent">Мандат</h2>
        <p className="text-xs text-qa-muted">
          Сколько капитала можно выставить в риск, какие тикеры запрещены, какие темы в новостях
          блокируют имя. Сохраните — правила учтутся при наборе книги. Потолок здесь не увеличивает
          операторский лимит счёта.
        </p>
        <div className="grid gap-3 md:grid-cols-2">
          <label className="text-xs text-qa-muted">
            Потолок книги
            <input
              className="mt-1 w-full rounded border border-cockpit-border bg-cockpit-bg px-2 py-1 text-qa-text"
              value={cap}
              onChange={(e) => setCap(e.target.value)}
            />
          </label>
          <label className="text-xs text-qa-muted">
            Дневной риск по мандату, %
            <input
              className="mt-1 w-full rounded border border-cockpit-border bg-cockpit-bg px-2 py-1 text-qa-text"
              value={risk}
              onChange={(e) => setRisk(e.target.value)}
            />
          </label>
          <label className="text-xs text-qa-muted md:col-span-2">
            Запрещённые тикеры — через запятую
            <input
              className="mt-1 w-full rounded border border-cockpit-border bg-cockpit-bg px-2 py-1 text-qa-text"
              value={banned}
              onChange={(e) => setBanned(e.target.value)}
              placeholder="TOX, XXX"
            />
          </label>
          <label className="text-xs text-qa-muted md:col-span-2">
            Темы в новостях, при которых имя блокируется
            <input
              className="mt-1 w-full rounded border border-cockpit-border bg-cockpit-bg px-2 py-1 text-qa-text"
              value={esg}
              onChange={(e) => setEsg(e.target.value)}
              placeholder="уголь, табак"
            />
          </label>
        </div>
        <button
          type="button"
          className="term-btn"
          onClick={() => saveIps.mutate()}
          disabled={saveIps.isPending}
        >
          Сохранить мандат
        </button>
        {saveIps.isError ? (
          <p className="text-xs text-red-400">Не удалось сохранить мандат. Попробуйте ещё раз.</p>
        ) : null}
        {saveIps.isSuccess ? <p className="text-xs text-emerald-400">Мандат записан</p> : null}
        {ipsQ.data?.updated_at ? (
          <p className="text-xs text-qa-muted">Обновлён: {ipsQ.data.updated_at}</p>
        ) : null}
      </section>

      <section className="cockpit-panel p-4 space-y-2">
        <h2 className="text-sm font-bold uppercase tracking-wide text-terminal-accent">Клиентский отчёт</h2>
        <p className="text-xs text-qa-muted">
          Что показать клиенту по бумажной книге: доходность к риску, просадка, доля прибыльных,
          вклад по составу. Ночной расчёт пишет сюда позиции; если пусто — отчёт ещё не считался.
        </p>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-2 text-sm">
          <div>
            Доходность к риску
            <div className="font-mono">{num(tear.sharpe)}</div>
          </div>
          <div>
            Макс. просадка
            <div className="font-mono">{num(tear.max_dd)}</div>
          </div>
          <div>
            Доля прибыльных
            <div className="font-mono">{num(tear.hit_rate)}</div>
          </div>
          <div>
            Доп. метрики
            <div className="font-mono">{tear.quantstats ? "есть" : "нет"}</div>
          </div>
        </div>
        <p className="text-xs text-qa-muted">
          Активный вклад {num(brinson.active)} · размещение {num(brinson.allocation)} · выбор{" "}
          {num(brinson.selection)}
        </p>
        {rc.length ? (
          <table className="w-full text-xs">
            <thead>
              <tr className="text-qa-muted">
                <th className="text-left">Имя</th>
                <th>вес</th>
                <th>доля риска, %</th>
              </tr>
            </thead>
            <tbody>
              {rc.slice(0, 12).map((row) => (
                <tr key={String(row.symbol)}>
                  <td>{String(row.symbol)}</td>
                  <td className="font-mono text-center">{num(row.weight)}</td>
                  <td className="font-mono text-center">{num(row.rc_pct)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <p className="text-xs text-qa-muted">нет данных — ночной отчёт ещё не писал книгу.</p>
        )}
      </section>

      <section className="cockpit-panel p-4 space-y-2">
        <h2 className="text-sm font-bold uppercase tracking-wide text-terminal-accent">Контроль данных</h2>
        <p className="text-xs text-qa-muted">
          Свежесть витрин и стабильность модели. Если данные устарели — новые сделки лучше не
          открывать, пока витрины не обновятся.
        </p>
        <p className="text-xs text-qa-muted">
          Свежесть: {monitor.freshness_ok ? "в норме" : "нарушена"} · дрейф:{" "}
          {monitor.drift?.alert ? "есть" : "нет"} · калибровка: {num(monitor.calibration?.ece)}
        </p>
        <ul className="text-xs space-y-1">
          {freshness.map((row) => (
            <li key={String(row.name)}>
              {String(row.name)}: {row.ok ? "ок" : "устарело"} · возраст {num(row.age_hours)}ч / норма{" "}
              {num(row.sla_hours)}ч
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}

export default function PlatformPage() {
  return (
    <div className="min-h-screen bg-cockpit-bg text-qa-text flex flex-col operator-shell">
      <NavBar activeTab="platform" />
      <AppPageShell title="Рабочий стол" description="Мандат книги, клиентский отчёт и контроль данных">
        <PageErrorBoundary>
          <PlatformDeskView />
        </PageErrorBoundary>
      </AppPageShell>
    </div>
  );
}
