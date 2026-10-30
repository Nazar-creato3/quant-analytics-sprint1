"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { Download, MessageCircle } from "lucide-react";
import { accountApi, forecastApi, portfolioApi } from "@/lib/api";
import { useAuth } from "@/hooks";
import { useProductContext } from "@/contexts/ProductContext";
import { Block, DASH, Quiet, Stat, StatGrid, pct } from "./ui";

const LIGHT: Record<string, { text: string; tone: "up" | "accent" | "down" | "neutral" }> = {
  green: { text: "Спокойный", tone: "up" },
  yellow: { text: "Повышенный", tone: "accent" },
  red: { text: "Высокий", tone: "down" },
};

/** First tab: what the portfolio is made of, how it did, how risky it is. */
export function OverviewBlock() {
  const { user } = useAuth();
  const { mode } = useProductContext();
  const uid = user?.id;
  const report = useQuery({
    queryKey: ["pf-report", uid, mode],
    enabled: Boolean(uid),
    queryFn: () => forecastApi.report(uid as string, mode),
  });
  const returns = useQuery({ queryKey: ["pf-returns", uid, mode], enabled: Boolean(uid), queryFn: () => accountApi.returns(uid as string, mode) });
  const first = report.data?.first_screen;
  const map = (first?.concentration_map ?? []) as Array<{ ticker: string; weight: string | number }>;
  const top = (first as Record<string, unknown> | undefined)?.top_holding as { ticker?: string; weight?: string | number } | undefined;
  const light = LIGHT[String(first?.traffic_light ?? "")];
  const scenarios = ((report.data?.stress as { scenarios?: Array<Record<string, unknown>> } | undefined)?.scenarios ?? []).slice(0, 6);
  const sample = useQuery({ queryKey: ["pf-sample"], queryFn: portfolioApi.sampleState });
  const maxW = Math.max(0.0001, ...map.map((r) => Number(r.weight) || 0));
  const twr = returns.data?.twr ?? first?.twr;
  const mwr = returns.data?.mwr ?? first?.mwr;

  const downloadPdf = async () => {
    if (!uid) return;
    const blob = await forecastApi.reportPdf(uid, mode);
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "portfolio-report.pdf";
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="space-y-5" data-testid="portfolio-report">
      <Block title="Сводка" hint="Доходность считается по вашим сделкам: «доходность решений» не зависит от пополнений, «рост денег» — то, что видно на счёте." method="/methodology">
        <StatGrid>
          <Stat label="Доходность решений" value={pct(twr) ?? DASH} tone={twr == null ? "neutral" : Number(twr) >= 0 ? "up" : "down"} sub="с начала, TWR" />
          <Stat label="Рост денег" value={pct(mwr) ?? DASH} tone={mwr == null ? "neutral" : Number(mwr) >= 0 ? "up" : "down"} sub="с начала, MWR" />
          <Stat label="Уровень риска" value={light?.text ?? DASH} tone={light?.tone ?? "neutral"} sub="по прошлым колебаниям" />
          <Stat label="Крупнейшая позиция" value={top?.ticker ?? DASH} sub={top?.weight != null ? `${pct(top.weight)} портфеля` : undefined} />
        </StatGrid>
        {!map.length && twr == null && !report.isLoading ? (
          // Empty for a reason the user can act on, not a silent row of dashes.
          <Quiet>
            {mode === "live"
              ? "На подключённом счёте брокера сейчас нет бумаг — считать риск и доходность не по чему. Пополните счёт или переключитесь в «Учебный», чтобы посмотреть расчёты на примере портфеля."
              : "В учебном портфеле пока нет позиций. Одобрите манёвр, купите бумагу или загрузите брокерский отчёт."}
          </Quiet>
        ) : twr == null && sample.data?.has_own_positions && returns.data?.load_report_hint ? (
          <Quiet>{returns.data.load_report_hint}</Quiet>
        ) : null}
        <div className="flex flex-wrap gap-2">
          <button type="button" className="btn-ghost text-xs inline-flex items-center gap-1.5" onClick={downloadPdf} data-testid="k6-pdf">
            <Download size={12} /> Скачать отчёт PDF
          </button>
          <Link href="/chat" className="btn-ghost text-xs inline-flex items-center gap-1.5">
            <MessageCircle size={12} /> Спросить ИИ о портфеле
          </Link>
        </div>
      </Block>

      {map.length ? (
        <Block title="Состав" hint="Доли бумаг в стоимости портфеля. Чем длиннее полоса, тем сильнее портфель зависит от этой бумаги.">
          <ul className="space-y-1.5" data-testid="report-composition">
            {map.slice(0, 15).map((row) => {
              const w = Number(row.weight) || 0;
              return (
                <li key={row.ticker} className="grid grid-cols-[90px_1fr_56px] items-center gap-3 text-xs">
                  <Link href={`/direct-deals?symbol=${encodeURIComponent(row.ticker)}`} className="font-medium hover:text-terminal-accent">
                    {row.ticker}
                  </Link>
                  <span className="h-2 rounded bg-cockpit-border/60 overflow-hidden">
                    <span className="block h-full rounded bg-terminal-accent" style={{ width: `${Math.min(100, (w / maxW) * 100)}%` }} />
                  </span>
                  <span className="text-right tabular-nums">{pct(w)}</span>
                </li>
              );
            })}
          </ul>
        </Block>
      ) : null}

      {scenarios.length ? (
        <Block title="Как портфель пережил бы прошлые кризисы" hint="Нынешний состав, прогнанный через реальные движения рынка в прошлом. Это не прогноз.">
          <ul className="grid gap-2 md:grid-cols-2" data-testid="report-stress">
            {scenarios.map((row) => {
              const raw = Number(row.pnl_pct ?? row.pnl ?? NaN);
              const frac = Number.isFinite(raw) ? (Math.abs(raw) <= 1 ? raw : raw / 100) : null;
              return (
                <li key={String(row.id ?? row.title)} className="rounded-lg border border-cockpit-border px-3 py-2 text-xs flex justify-between gap-3">
                  <span>{String(row.title ?? "Сценарий")}</span>
                  <span className={`tabular-nums font-semibold ${frac != null && frac < 0 ? "text-terminal-down" : "text-terminal-up"}`}>
                    {frac == null ? DASH : pct(frac)}
                  </span>
                </li>
              );
            })}
          </ul>
        </Block>
      ) : null}
    </div>
  );
}
