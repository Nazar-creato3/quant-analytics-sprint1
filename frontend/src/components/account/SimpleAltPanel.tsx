"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { accountApi, type SimpleAltResponse } from "@/lib/api";
import { fetchUiTexts } from "@/lib/legal-docs";
import { useProductContext } from "@/contexts/ProductContext";
import { queryKeys } from "@/lib/queryKeys";

type K1Texts = {
  title?: string;
  twr?: string;
  mwr?: string;
  portfolio?: string;
  end_value?: string;
  diff_value?: string;
  diff_twr?: string;
  diff_mwr?: string;
  same_flows?: string;
  source?: string;
  past?: string;
  method_link?: string;
  no_judgment?: string;
};

function cell(value: string | null | undefined): string {
  if (value == null || value === "") return "нет данных";
  return value;
}

function sourceLine(template: string | undefined, source?: string | null, asOf?: string | null): string {
  if (!template) return "";
  return template.replace("{source}", source || "нет данных").replace("{as_of}", asOf || "нет данных");
}

export function SimpleAltPanel({ userId }: { userId?: string }) {
  const { mode } = useProductContext();
  const { data: texts } = useQuery({
    queryKey: ["legal-ui-texts-k1"],
    queryFn: async () => {
      try {
        const data = (await fetchUiTexts()) as { k1?: K1Texts };
        return data.k1 ?? {};
      } catch {
        return {};
      }
    },
    staleTime: 60_000,
  });
  const t = texts ?? {};
  const { data, isError } = useQuery({
    queryKey: queryKeys.simpleAlts(userId || "anonymous", mode),
    enabled: Boolean(userId),
    queryFn: () => accountApi.simpleAlts(userId as string, mode),
  });

  if (!userId) return null;
  if (isError) {
    return (
      <div className="mt-4 rounded-lg border border-cockpit-border p-3" data-testid="k1-simple-alt">
        <p className="text-xs text-qa-muted">нет данных</p>
      </div>
    );
  }
  if (!data) return null;

  const payload = data as SimpleAltResponse;
  const alts = payload.alternatives ?? [];

  return (
    <div className="mt-4 rounded-lg border border-cockpit-border p-3 space-y-2" data-testid="k1-simple-alt">
      <p className="text-[10px] uppercase tracking-wide text-qa-muted">{t.title || "нет данных"}</p>
      <p className="text-xs text-qa-muted">{t.same_flows}</p>
      {payload.data_status && payload.data_status !== "ok" ? (
        <p className="text-xs text-terminal-accent" data-testid="k1-status">
          {payload.data_status}
          {payload.reason ? `: ${payload.reason}` : ""}
        </p>
      ) : null}
      <table className="w-full text-xs font-mono" data-testid="k1-table">
        <thead>
          <tr className="text-qa-muted text-left">
            <th />
            <th className="text-right">{t.end_value}</th>
            <th className="text-right">{t.twr}</th>
            <th className="text-right">{t.mwr}</th>
            <th className="text-right">{t.diff_value}</th>
            <th className="text-right">{t.diff_twr}</th>
            <th className="text-right">{t.diff_mwr}</th>
          </tr>
        </thead>
        <tbody>
          <tr data-testid="k1-portfolio">
            <td>{t.portfolio}</td>
            <td className="text-right">{cell(payload.portfolio?.end_value)}</td>
            <td className="text-right">{cell(payload.portfolio?.twr)}</td>
            <td className="text-right">{cell(payload.portfolio?.mwr)}</td>
            <td className="text-right">—</td>
            <td className="text-right">—</td>
            <td className="text-right">—</td>
          </tr>
          {alts.map((row) => (
            <tr key={row.ticker} data-testid={`k1-alt-${row.ticker}`}>
              <td>{row.label || row.ticker}</td>
              <td className="text-right">{cell(row.end_value)}</td>
              <td className="text-right">{cell(row.twr)}</td>
              <td className="text-right">{cell(row.mwr)}</td>
              <td className="text-right">{cell(row.diff_value)}</td>
              <td className="text-right">{cell(row.diff_twr_pp)}</td>
              <td className="text-right">{cell(row.diff_mwr_pp)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {alts.map((row) => (
        <p key={`${row.ticker}-src`} className="text-[11px] text-qa-muted" data-testid={`k1-source-${row.ticker}`}>
          {sourceLine(t.source, row.source, row.price_as_of)}
        </p>
      ))}
      <p className="text-[11px] text-qa-muted">{t.past}</p>
      <p className="text-[11px] text-qa-muted">{t.no_judgment}</p>
      <Link className="text-[11px] text-terminal-accent underline" href="/methodology">
        {t.method_link || "нет данных"}
      </Link>
    </div>
  );
}
