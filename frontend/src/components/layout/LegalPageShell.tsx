"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { LegalFooter } from "@/components/layout/LegalFooter";
import { OPERATOR } from "@/content/legal/operator";

export type LegalSection = {
  id?: string;
  title: string;
  paragraphs: string[];
  list?: string[];
};

type LegalPageShellProps = {
  title: string;
  subtitle?: string;
  sections: LegalSection[];
  backHref?: string;
  backLabel?: string;
};

export function LegalPageShell({
  title,
  subtitle,
  sections,
  backHref,
  backLabel = "← Назад",
}: LegalPageShellProps) {
  const router = useRouter();

  const handleBack = () => {
    if (backHref) {
      router.push(backHref);
      return;
    }
    if (typeof window !== "undefined" && window.history.length > 1) {
      router.back();
      return;
    }
    router.push("/");
  };

  return (
    <div className="min-h-screen bg-qa-bg flex flex-col items-center px-4 py-10">
      <article className="w-full max-w-2xl card p-6 sm:p-8 space-y-6">
        <header className="space-y-2 border-b border-qa-border pb-4">
          <p className="text-[10px] uppercase tracking-wider text-qa-muted font-mono">
            Quant Analytics
          </p>
          <h1 className="text-xl sm:text-2xl font-bold text-qa-text tracking-tight">{title}</h1>
          {subtitle ? <p className="text-sm text-qa-muted leading-relaxed">{subtitle}</p> : null}
        </header>

        <div className="space-y-6 text-sm text-qa-muted leading-relaxed">
          {sections.map((section) => (
            <section key={section.id ?? section.title} id={section.id} className="space-y-2">
              <h2 className="text-[13px] font-semibold text-qa-text tracking-tight">{section.title}</h2>
              {section.paragraphs.map((paragraph) => (
                <p key={paragraph.slice(0, 48)}>{paragraph}</p>
              ))}
              {section.list ? (
                <ul className="list-disc pl-5 space-y-1 marker:text-terminal-accent">
                  {section.list.map((item) => (
                    <li key={item.slice(0, 48)}>{item}</li>
                  ))}
                </ul>
              ) : null}
            </section>
          ))}
        </div>

        <footer className="pt-2 border-t border-qa-border">
          <p className="text-xs text-qa-muted">
            Вопросы:{" "}
            <Link
              href={`mailto:${OPERATOR.email}`}
              className="text-terminal-accent hover:text-terminal-accent"
            >
              {OPERATOR.email}
            </Link>
          </p>
          <button
            type="button"
            onClick={handleBack}
            className="inline-block mt-3 text-sm text-terminal-accent hover:text-terminal-accent"
          >
            {backLabel}
          </button>
        </footer>
      </article>
      <LegalFooter />
    </div>
  );
}
