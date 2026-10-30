"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { NavBar } from "@/components/layout/NavBar";
import { AppPageShell } from "@/components/layout/AppPageShell";
import { fetchUiTexts } from "@/lib/legal-docs";

type TaxTexts = {
  method_title?: string;
  method_intro?: string;
  method_limits?: string;
  lawyer_unconfirmed?: string;
  method_link?: string;
  no_data?: string;
};

export default function TaxMethodologyPage() {
  const { data: t } = useQuery({
    queryKey: ["legal-ui-texts-tax-method"],
    queryFn: async () => {
      try {
        const data = (await fetchUiTexts()) as { tax?: TaxTexts };
        return data.tax ?? {};
      } catch {
        return {} as TaxTexts;
      }
    },
    staleTime: 60_000,
  });
  const texts = t ?? {};
  const empty = texts.no_data ?? "нет данных";

  return (
    <div className="min-h-screen bg-cockpit-bg text-qa-text flex flex-col">
      <NavBar activeTab="tax-rf" />
      <AppPageShell title={texts.method_title || empty}>
        <article className="prose prose-invert max-w-3xl text-sm space-y-3" data-testid="k3-tax-method">
          <p data-testid="tax-lawyer-disclaimer">{texts.lawyer_unconfirmed || empty}</p>
          <p>{texts.method_intro || empty}</p>
          <p>{texts.method_limits || empty}</p>
          <p>
            <Link className="underline" href="/portfolio?tab=costs">
              {texts.method_link || empty}
            </Link>
          </p>
        </article>
      </AppPageShell>
    </div>
  );
}
