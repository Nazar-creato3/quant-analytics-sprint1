import { BackButton } from "@/components/layout/BackButton";
export default function LiquidityMethodologyPage() {
  return (
    <main className="mx-auto max-w-3xl p-4">
      <BackButton className="mb-3" />
      <h1 className="text-lg font-medium">Методика: ликвидность</h1>
      <p className="mt-2 text-sm text-qa-muted">
        Дней на выход = стоимость позиции / (доля участия × медиана оборота за 20 дней). Влияние на цену ≈ Y ·
        σ_дн · √(Q/ADV) плюс половина спреда (Y=1). Нет оборота — «нет сделок», не ноль и не бесконечность. Стресс —
        оборот 50% от обычного. Облигации без сделок 10+ дней из 60 — «редкие сделки».
      </p>
    </main>
  );
}
