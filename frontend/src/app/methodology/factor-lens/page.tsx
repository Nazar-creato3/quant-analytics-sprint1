"use client";

import Link from "next/link";
import { NavBar } from "@/components/layout/NavBar";
import { AppPageShell } from "@/components/layout/AppPageShell";

export default function FactorLensMethodologyPage() {
  return (
    <div className="min-h-screen bg-cockpit-bg text-qa-text flex flex-col">
      <NavBar activeTab="factors" />
      <AppPageShell title="Методика: российские факторы">
        <article className="prose prose-invert max-w-3xl text-sm space-y-3" data-testid="k65-method">
          <p>
            Формулы в репозитории: docs/methodology/factor-lens.md. Экран показывает расчёт по вашим
            позициям, не совет.
          </p>
          <p>
            Порядок ортогонализации: рынок → ставка → кредит → рубль → нефть → размер → стоимость →
            моментум → дивиденды. Каждый следующий ряд — остаток регрессии на предыдущие.
          </p>
          <p>
            ENB — exp(−Σ p ln p) по главным компонентам и отдельно по факторам минимального кручения.
            R² портфеля ниже 0,5 помечается отдельно.
          </p>
          <p>
            <Link className="underline" href="/portfolio?tab=risk">
              К рядам факторов
            </Link>
            {" · "}
            <Link className="underline" href="/portfolio?tab=risk">
              К экрану риска
            </Link>
            {" · "}
            <Link className="underline" href="/methodology">
              Обзор методики
            </Link>
          </p>
        </article>
      </AppPageShell>
    </div>
  );
}
