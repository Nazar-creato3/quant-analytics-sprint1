"use client";

import Link from "next/link";
import { NavBar } from "@/components/layout/NavBar";
import { AppPageShell } from "@/components/layout/AppPageShell";

export default function DecisionCoreMethodPage() {
  return (
    <div className="min-h-screen bg-cockpit-bg text-qa-text">
      <NavBar activeTab="dashboard" />
      <AppPageShell title="Методика: главное сейчас">
        <p className="text-sm">
          Список читает уже посчитанные цифры модулей. Своих цен и риска он не считает.
          Уверенность — это статус данных модуля. Через 1, 3 и 6 месяцев журнал сверяется с ценой решений.
          Теневые веса не меняют порядок на экране.
        </p>
        <Link className="underline text-xs" href="/">
          На дашборд
        </Link>
      </AppPageShell>
    </div>
  );
}
