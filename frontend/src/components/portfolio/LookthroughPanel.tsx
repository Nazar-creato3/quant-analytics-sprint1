"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { portfolioApi } from "@/lib/api";
import { fetchUiTexts } from "@/lib/legal-docs";
import { useProductContext } from "@/contexts/ProductContext";
import { queryKeys } from "@/lib/queryKeys";

type LookTexts = {
  title?: string;
  view_broker?: string;
  view_lookthrough?: string;
  hidden_title?: string;
  hidden_line?: string;
  overlap_title?: string;
  overlap_hint?: string;
  as_of?: string;
  stale?: string;
  partial?: string;
  no_data?: string;
  method_link?: string;
  basis?: string;
  undisclosed?: string;
};

function pct(raw: string | undefined): string {
  if (raw == null || raw === "") return "нет данных";
  const n = Number(raw);
  if (!Number.isFinite(n)) return "нет данных";
  return `${(n * 100).toFixed(1)}%`;
}

export function LookthroughPanel() {
  const { activeAccount, mode } = useProductContext();
  const [view, setView] = useState<"broker" | "lookthrough">("lookthrough");
  const { data: texts } = useQuery({
    queryKey: ["legal-ui-texts-lookthrough"],
    queryFn: async () => {
      try {
        const data = (await fetchUiTexts()) as { lookthrough?: LookTexts };
        return data.lookthrough ?? {};
      } catch {
        return {};
      }
    },
    staleTime: 60_000,
  });
  const t = texts ?? {};
  const { data, isLoading, isError } = useQuery({
    queryKey: queryKeys.lookthrough(activeAccount, mode, view),
    queryFn: () => portfolioApi.lookthrough("me", mode, "issuer", view),
  });

  if (isLoading) {
    return <p className="text-xs text-qa-muted">загрузка…</p>;
  }
  if (isError || !data || data.data_status === "нет данных") {
    return (
      <div className="cockpit-panel p-4" data-testid="k61-lookthrough">
        <p className="text-sm">{t.no_data || "нет данных"}</p>
      </div>
    );
  }

  return (
    <div className="cockpit-panel p-4 space-y-3" data-testid="k61-lookthrough">
      <div className="cockpit-panel-header">{t.title || "нет данных"}</div>
      <p className="text-[11px] text-qa-muted">
        {(t.basis || "Источник: {source}. Состав на {as_of}.")
          .replace("{source}", data.source || "нет данных")
          .replace("{as_of}", data.as_of || "нет данных")}{" "}
        <Link href="/methodology/fund-look-through" className="underline">
          {t.method_link || "/methodology"}
        </Link>
      </p>
      {data.stale ? <p className="text-xs">{t.stale}</p> : null}
      {data.data_status === "частично" ? (
        <p className="text-xs" data-testid="k61-partial">
          {t.partial}
          {data.reason ? `: ${data.reason}` : ""}
        </p>
      ) : null}
      <div className="flex gap-2 text-xs">
        <button
          type="button"
          data-testid="k61-view-broker"
          className={view === "broker" ? "underline" : ""}
          onClick={() => setView("broker")}
        >
          {t.view_broker}
        </button>
        <button
          type="button"
          data-testid="k61-view-lookthrough"
          className={view === "lookthrough" ? "underline" : ""}
          onClick={() => setView("lookthrough")}
        >
          {t.view_lookthrough}
        </button>
      </div>
      {!data.rows.length ? (
        <p className="text-sm">{t.no_data || "нет данных"}</p>
      ) : (
        <table className="w-full text-xs font-mono" data-testid="k61-table">
          <tbody>
            {data.rows.map((row) => (
              <tr key={row.key}>
                <td>{row.key}</td>
                <td>{row.disclosed === false ? t.undisclosed : pct(row.weight)}</td>
                <td className="text-qa-muted">{row.as_of || "нет данных"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {view === "lookthrough" && (data.hidden?.length ?? 0) > 0 ? (
        <div data-testid="k61-hidden">
          <p className="text-xs">{t.hidden_title}</p>
          {data.hidden?.map((card) => (
            <p key={card.issuer} className="text-sm">
              {(t.hidden_line || "{issuer} {lookthrough}")
                .replace("{issuer}", card.issuer)
                .replace("{lookthrough}", pct(card.lookthrough))
                .replace("{direct}", pct(card.direct))}
            </p>
          ))}
        </div>
      ) : null}
      {view === "lookthrough" && (data.overlaps?.length ?? 0) > 0 ? (
        <div data-testid="k61-overlap">
          <p className="text-xs">{t.overlap_title}</p>
          <p className="text-[11px] text-qa-muted">{t.overlap_hint}</p>
          <table className="w-full text-xs font-mono">
            <tbody>
              {data.overlaps?.map((row) => (
                <tr key={`${row.left}-${row.right}`}>
                  <td>
                    {row.left} × {row.right}
                  </td>
                  <td>{pct(row.overlap)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </div>
  );
}
