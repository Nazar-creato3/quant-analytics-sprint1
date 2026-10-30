"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { LegalFooter } from "@/components/layout/LegalFooter";
import { PRIVACY_SECTIONS } from "@/content/legal/privacy";
import { TERMS_SECTIONS } from "@/content/legal/terms";
import { fetchLegalDocument, fetchUiTexts, type LegalDocument } from "@/lib/legal-docs";

export function LegalMarkdownPage({
  code,
  version,
}: {
  code: string;
  version?: string;
}) {
  const [doc, setDoc] = useState<LegalDocument | null>(null);
  const [badge, setBadge] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    let alive = true;
    Promise.all([
      fetchLegalDocument(code, version),
      fetchUiTexts().catch((): Record<string, unknown> => ({})),
    ])
      .then(([row, texts]) => {
        if (!alive) return;
        setDoc(row);
        const rawBadge = texts["legal_draft_badge"];
        const label = typeof rawBadge === "string" ? rawBadge : "Редакция на проверке";
        setBadge(row.draft_badge ? label : "");
      })
      .catch((err: Error) => {
        if (!alive) return;
        setError(err.message || "нет данных");
      });
    return () => {
      alive = false;
    };
  }, [code, version]);

  return (
    <div
      className="min-h-screen bg-qa-bg flex flex-col items-center px-4 py-10"
      data-legacy-legal={TERMS_SECTIONS.length + PRIVACY_SECTIONS.length}
    >
      <article className="w-full max-w-2xl card p-6 sm:p-8 space-y-6">
        {error ? <p className="text-sm text-qa-muted">Текст не загружен: {error}</p> : null}
        {!error && !doc ? <p className="text-sm text-qa-muted">Загрузка…</p> : null}
        {doc ? (
          <>
            {badge ? (
              <p className="text-[11px] uppercase tracking-wider text-qa-muted font-mono">{badge}</p>
            ) : null}
            <pre className="whitespace-pre-wrap text-sm text-qa-muted leading-relaxed font-sans">
              {doc.body}
            </pre>
            <p className="text-[11px] text-qa-muted font-mono">
              {doc.code} {doc.version} {doc.status} {doc.sha256.slice(0, 12)}
            </p>
          </>
        ) : null}
        <p className="text-xs text-qa-muted">
          <Link href="/legal/terms" className="text-terminal-accent">
            /legal/{code}
            {version ? `/${version}` : ""}
          </Link>
        </p>
      </article>
      <LegalFooter />
    </div>
  );
}
