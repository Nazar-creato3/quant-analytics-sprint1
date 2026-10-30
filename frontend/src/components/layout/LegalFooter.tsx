import Link from "next/link";
import { OPERATOR, operatorLine } from "@/content/legal/operator";

/** Documents every page must link to (152-FZ art. 18.1; 149-FZ art. 10.2-2). */
export const LEGAL_LINKS: ReadonlyArray<{ href: string; label: string }> = [
  { href: "/legal/terms", label: "Пользовательское соглашение" },
  { href: "/legal/privacy", label: "Политика обработки персональных данных" },
  { href: "/legal/consent", label: "Согласие на обработку данных" },
  { href: "/legal/recommendations", label: "Рекомендательные технологии" },
  { href: "/legal/disclaimer", label: "О характере информации" },
  { href: "/legal/cookies", label: "Cookie" },
  { href: "/legal/entity", label: "Сведения об операторе" },
];

/**
 * One quiet line; the documents open under "Документы".
 * The links stay in the page markup while folded, so every document remains
 * reachable from every page (and by search robots) without taking space.
 */
export function LegalFooter({ compact = false }: { compact?: boolean }) {
  return (
    <footer
      className={
        compact
          ? "text-[10px] text-qa-muted px-2 py-2"
          : "text-center text-[11px] text-qa-muted mt-8 px-4 pb-6"
      }
      data-testid="legal-footer"
    >
      <details className="group">
        <summary
          className="list-none cursor-pointer select-none inline-flex flex-wrap items-center justify-center gap-x-2 [&::-webkit-details-marker]:hidden"
          data-testid="legal-footer-toggle"
        >
          <span>© {new Date().getFullYear()} {OPERATOR.shortName}</span>
          <span aria-hidden>·</span>
          <span className="underline decoration-dotted underline-offset-2 hover:text-qa-text transition-colors">
            Документы
            <span className="inline-block ml-0.5 transition-transform group-open:rotate-180" aria-hidden>
              ▾
            </span>
          </span>
          <span aria-hidden>·</span>
          <span>Не является инвестиционной рекомендацией</span>
          <span aria-hidden>·</span>
          <span>18+</span>
        </summary>
        <div className="mt-2 space-y-1.5">
          <nav className="flex flex-wrap items-center justify-center gap-x-3 gap-y-1" aria-label="Документы">
            {LEGAL_LINKS.map((l) => (
              <Link key={l.href} href={l.href} className="hover:text-qa-text transition-colors">
                {l.label}
              </Link>
            ))}
          </nav>
          <p>
            Не является индивидуальной инвестиционной рекомендацией. Решения о сделках принимает пользователь.
            Инвестиции связаны с риском потери средств.
          </p>
          <p>
            {operatorLine()} ·{" "}
            <a href={`mailto:${OPERATOR.email}`} className="hover:text-qa-text transition-colors">
              {OPERATOR.email}
            </a>
          </p>
        </div>
      </details>
    </footer>
  );
}
