"use client";

import { useMutation, useQuery } from "@tanstack/react-query";
import { AppPageShell } from "@/components/layout/AppPageShell";
import { fetchUiTexts } from "@/lib/legal-docs";
import { forecastApi } from "@/lib/api";

type K6Texts = Record<string, string>;

export default function StatementReviewPage() {
  const { data: texts } = useQuery({
    queryKey: ["legal-ui-texts-k6"],
    queryFn: fetchUiTexts,
    staleTime: 60_000,
  });
  const t = ((texts?.k6 as K6Texts) || {}) as K6Texts;
  const demo = useQuery({
    queryKey: ["k6-statement-demo"],
    queryFn: () => forecastApi.statementDemo(),
  });
  const upload = useMutation({
    mutationFn: (file: File) => forecastApi.statementUpload(file),
  });
  const parsed = upload.data?.parsed || demo.data?.parsed;
  return (
    <div className="min-h-screen bg-cockpit-bg text-qa-text">
      <AppPageShell title={t.statement_title || ""} description={t.statement_demo || ""}>
        <div className="cockpit-panel p-4 space-y-3" data-testid="k6-statement">
          <p className="text-xs" data-testid="k6-statement-demo">
            {t.statement_demo}
          </p>
          <p className="text-xs text-qa-muted">
            {t.broker}: {t.tbank}
          </p>
          <label className="text-xs block">
            {t.statement_upload}
            <input
              data-testid="k6-statement-file"
              className="block mt-1"
              type="file"
              accept=".xml,.xlsx,.csv"
              onChange={(event) => {
                const file = event.target.files?.[0];
                if (file) upload.mutate(file);
              }}
            />
          </label>
          {(parsed?.positions || []).length ? (
            <ul className="text-xs space-y-1" data-testid="k6-statement-rows">
              {(parsed?.positions || []).map((row) => (
                <li key={row.ticker}>
                  {row.ticker} · {row.qty} · {row.amount}
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-xs text-qa-muted">нет данных</p>
          )}
          <p className="text-xs" data-testid="k6-file-deleted">
            {t.file_deleted}
          </p>
          <p className="text-xs text-qa-muted">{t.mail_wait}</p>
          <a
            className="text-xs underline text-terminal-accent"
            data-testid="k6-statement-pdf"
            href="/api/v1/report/statement/demo.pdf"
          >
            {t.pdf_download}
          </a>
        </div>
      </AppPageShell>
    </div>
  );
}
