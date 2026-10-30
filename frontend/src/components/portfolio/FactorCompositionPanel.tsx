"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { portfolioApi } from "@/lib/api";
import { fetchUiTexts } from "@/lib/legal-docs";

type FactorTexts = {
  composition_title?: string;
  composition_hint?: string;
  enb?: string;
  enb_of?: string;
  enb_hint?: string;
  low_r2?: string;
  method_link?: string;
  basis?: string;
  partial?: string;
  no_data?: string;
};

const LABELS: Record<string, string> = {
  market: "рынок",
  rates: "ставка",
  credit: "кредит",
  fx: "рубль",
  oil: "нефть",
  size: "размер",
  value: "стоимость",
  momentum: "моментум",
  dividends: "дивиденды",
  idiosyncratic: "собственный риск бумаг",
};

function pct(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return "нет данных";
  return `${(value * 100).toFixed(1)}%`;
}

export function FactorCompositionPanel() {
  const { data: texts } = useQuery({
    queryKey: ["legal-ui-texts-factors"],
    queryFn: async () => {
      try {
        const data = (await fetchUiTexts()) as { factors?: FactorTexts };
        return data.factors ?? {};
      } catch {
        return {};
      }
    },
    staleTime: 60_000,
  });
  const t = texts ?? {};
  const { data, isError } = useQuery({
    queryKey: ["portfolio-factors"],
    queryFn: () => portfolioApi.portfolioFactors("me"),
  });

  const shares = data?.risk_shares ?? {};
  const rows = Object.entries(LABELS)
    .map(([key, label]) => ({ key, label, share: shares[key] as number | null | undefined }))
    .filter((row) => row.share != null);

  // Nothing computed (no price history yet) → the block is not shown at all.
  if (isError || !rows.length) return null;

  return (
    <section className="card p-5 space-y-3" data-testid="k65-composition">
      <header className="flex items-start justify-between gap-3">
        <div>
          <h2 className="text-sm font-semibold">{t.composition_title || "Из чего состоит ваш риск"}</h2>
          {data?.sentence ? <p className="text-xs text-qa-muted mt-1 max-w-2xl">{data.sentence}</p> : null}
        </div>
        <Link href="/methodology/factor-lens" className="shrink-0 text-[11px] text-qa-muted hover:text-terminal-accent hover:underline">
          {t.method_link || "Как считается"}
        </Link>
      </header>
      {data?.data_status === "частично" ? (
        <p className="text-xs text-terminal-accent" data-testid="k65-partial">
          {t.partial}
          {data.reason ? `: ${data.reason}` : ""}
        </p>
      ) : null}
      {data?.quality_note ? (
        <p className="text-xs" data-testid="k65-low-r2">
          {data.quality_note}
        </p>
      ) : null}
      <ul className="space-y-1.5" data-testid="k65-table">
        {rows.map((row) => (
          <li key={row.key} className="grid grid-cols-[minmax(120px,200px)_1fr_56px] items-center gap-3 text-xs">
            <span>{row.label}</span>
            <span className="h-2 rounded bg-cockpit-border/60 overflow-hidden">
              <span className="block h-full rounded bg-terminal-accent" style={{ width: `${Math.min(100, Math.abs(Number(row.share)) * 100)}%` }} />
            </span>
            <span className="text-right tabular-nums">{pct(row.share)}</span>
          </li>
        ))}
      </ul>
      {data?.enb != null && Number.isFinite(Number(data.enb)) ? (
        <p className="text-xs" data-testid="k65-enb">
          {t.enb}: <b className="tabular-nums">{Number(data.enb).toFixed(1)}</b>{" "}
          {(t.enb_of || "из {n} бумаг").replace("{n}", String(data?.n_names ?? "—"))}
        </p>
      ) : null}
      {t.enb_hint ? <p className="text-[11px] text-qa-muted">{t.enb_hint}</p> : null}
    </section>
  );
}
