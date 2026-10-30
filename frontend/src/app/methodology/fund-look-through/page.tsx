"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { NavBar } from "@/components/layout/NavBar";
import { AppPageShell } from "@/components/layout/AppPageShell";
import { fetchUiTexts } from "@/lib/legal-docs";

type LookTexts = {
  method_title?: string;
  method_intro?: string;
  method_expand?: string;
  method_index?: string;
  structure_link?: string;
  method_overview?: string;
};

export default function FundLookThroughMethodologyPage() {
  const { data: t } = useQuery({
    queryKey: ["legal-ui-texts-lookthrough-method"],
    queryFn: async () => {
      try {
        const data = (await fetchUiTexts()) as { lookthrough?: LookTexts };
        return data.lookthrough ?? {};
      } catch {
        return {} as LookTexts;
      }
    },
    staleTime: 60_000,
  });
  const texts = t ?? {};

  return (
    <div className="min-h-screen bg-cockpit-bg text-qa-text flex flex-col">
      <NavBar activeTab="portfolio-risk" />
      <AppPageShell title={texts.method_title || "нет данных"}>
        <article className="prose prose-invert max-w-3xl text-sm space-y-3" data-testid="k61-method">
          <p>{texts.method_intro || "нет данных"}</p>
          <p>{texts.method_expand || "нет данных"}</p>
          <p>{texts.method_index || "нет данных"}</p>
          <p>
            <Link className="underline" href="/portfolio-structure">
              {texts.structure_link || "нет данных"}
            </Link>
            {" · "}
            <Link className="underline" href="/methodology">
              {texts.method_overview || "нет данных"}
            </Link>
          </p>
        </article>
      </AppPageShell>
    </div>
  );
}
