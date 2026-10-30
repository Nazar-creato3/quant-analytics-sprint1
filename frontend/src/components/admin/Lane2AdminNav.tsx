import Link from "next/link";

export function Lane2AdminNav() {
  return (
    <nav className="flex flex-wrap gap-3 p-4 text-sm text-neutral-700" aria-label="Админка полосы 2">
      <Link href="/admin/analytics">Метрики основателя</Link>
      <Link href="/admin/experiments">Эксперименты</Link>
      <Link href="/admin/beta">Админка беты</Link>
    </nav>
  );
}
