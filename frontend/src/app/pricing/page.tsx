export default function PricingPage() {
  return (
    <main className="mx-auto max-w-3xl bg-white p-4 text-neutral-800">
      <h1 className="text-lg font-medium">Тариф</h1>
      <p className="mt-2 text-sm">Личный план: 10&nbsp;000 RUB в месяц.</p>
      <p className="mt-2 text-sm text-neutral-600">
        Оплата на сайте выключена (флаг qa_payment), пока подписка не утверждена.
      </p>
      <p className="mt-2 text-sm text-neutral-600">Годовой тариф: нет данных.</p>
    </main>
  );
}
