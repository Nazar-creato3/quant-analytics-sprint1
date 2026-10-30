import Link from "next/link";
import { LegalFooter } from "@/components/layout/LegalFooter";
import { siteSections } from "@/lib/public-site";

export function PublicSiteHome() {
  const sections = siteSections();
  return (
    <main className="mx-auto max-w-3xl bg-white p-4 text-neutral-800">
      <h1 className="text-lg font-medium">Quant Analytics</h1>
      {sections.map((section) => (
        <section key={section.title} className="mt-4">
          <h2 className="text-sm font-medium">{section.title}</h2>
          <p className="mt-1 text-sm text-neutral-700">{section.body}</p>
        </section>
      ))}
      <nav className="mt-4 flex flex-col gap-1 text-sm" aria-label="Публичные страницы">
        <Link href="/methodology">Методика</Link>
        <Link href="/pricing">Тариф</Link>
        <Link href="/site/accuracy">Точность прогнозов</Link>
        <Link href="/site/team">Команда</Link>
        <Link href="/site/contacts">Контакты</Link>
      </nav>
      <LegalFooter />
    </main>
  );
}
