import Link from "next/link";
import { LegalFooter, LEGAL_LINKS } from "@/components/layout/LegalFooter";

export default function LegalIndexPage() {
  return (
    <div className="min-h-screen bg-qa-bg flex flex-col items-center px-4 py-10">
      <article className="w-full max-w-2xl card p-6 sm:p-8 space-y-4">
        <h1 className="text-lg font-semibold">Документы</h1>
        <ul className="space-y-2 text-sm">
          {LEGAL_LINKS.map((l) => (
            <li key={l.href}>
              <Link href={l.href} className="text-terminal-accent hover:underline">
                {l.label}
              </Link>
            </li>
          ))}
          <li>
            <Link href="/legal/consent_broker" className="text-terminal-accent hover:underline">
              Согласие на обработку данных брокерского счёта
            </Link>
          </li>
          <li>
            <Link href="/legal/subscription" className="text-terminal-accent hover:underline">
              Условия подписки
            </Link>
          </li>
        </ul>
      </article>
      <LegalFooter />
    </div>
  );
}
