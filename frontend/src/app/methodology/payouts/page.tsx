import { BackButton } from "@/components/layout/BackButton";
export default function PayoutsMethodologyPage() {
  return (
    <main className="mx-auto max-w-3xl p-4">
      <BackButton className="mb-3" />
      <h1 className="text-lg font-medium">Методика: календарь выплат</h1>
      <p className="mt-2 text-sm text-qa-muted">
        События — объявленные и рекомендованные дивиденды (T-Invest GetDividends), история ISS
        /iss/securities/{"{{secid}}"}/dividends.json, выплаты фондов тем же методом. Облигации — из
        bond_cashflow_events после слияния 56. Последний день покупки: поле брокера либо предыдущий
        торговый день Мосбиржи перед record (T+1), пометка «расчёт». НДФЛ 13% с пометкой до K3; иностранные
        бумаги — «налог может отличаться», без числа. Ориентир estimated: дата по прошлым годам, размер не
        ставится. Гэп — среднее и медиана открытия после отсечки за 5 лет, «по прошлым данным, не прогноз».
        Нет данных — «нет данных».
      </p>
    </main>
  );
}
