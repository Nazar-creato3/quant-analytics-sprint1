"use client";

import { useQuery } from "@tanstack/react-query";
import { useParams } from "next/navigation";
import Link from "next/link";
import { NavBar } from "@/components/layout/NavBar";
import { AppPageShell } from "@/components/layout/AppPageShell";
import { fetchUiTexts } from "@/lib/legal-docs";
import { portfolioApi } from "@/lib/api";

export default function BondCardPage() {
  const params = useParams<{ figi: string }>();
  const figi = String(params.figi || "");
  const { data: texts } = useQuery({
    queryKey: ["legal-ui-texts-bonds"],
    queryFn: async () => ((await fetchUiTexts()) as { bonds?: Record<string, string> }).bonds ?? {},
  });
  const { data, isLoading, error } = useQuery({
    queryKey: ["bond-card", figi],
    queryFn: () => portfolioApi.bondCard(figi),
    enabled: Boolean(figi),
  });
  const t = texts ?? {};
  return (
    <div className="min-h-screen bg-cockpit-bg text-qa-text flex flex-col operator-shell">
      <NavBar activeTab="portfolio-bonds" />
      <AppPageShell title={figi}>
        <section className="cockpit-panel p-4" data-testid="bond-card">
          {isLoading ? <p>загрузка</p> : null}
          {error || data?.status === "нет данных" ? <p>{t.no_data ?? "нет данных"}</p> : null}
          {data && data.status !== "нет данных" ? (
            <>
              <p className="text-sm">
                {t.ytm}: {data.ytm == null ? t.no_data : `${(data.ytm * 100).toFixed(2)}%`}
              </p>
              <p className="text-xs text-qa-muted">
                {(t.source ?? "Источник: {source}, дата данных: {as_of}.")
                  .replace("{source}", String(data.source ?? "нет данных"))
                  .replace("{as_of}", String(data.as_of ?? "нет данных"))}
              </p>
              <h3 className="mt-3 text-xs">{t.card_flows}</h3>
              <ul data-testid="bond-flows">
                {(data.cashflows || []).map((cf: { on_date: string; amount_per_bond: number; type_label?: string }) => (
                  <li key={`${cf.on_date}-${cf.type_label}`}>
                    {cf.on_date} · {cf.type_label || "выплата"} · {cf.amount_per_bond}
                  </li>
                ))}
              </ul>
              <Link className="text-xs underline mt-3 inline-block" href="/methodology/bonds">
                {t.method_link}
              </Link>
            </>
          ) : null}
        </section>
      </AppPageShell>
    </div>
  );
}
