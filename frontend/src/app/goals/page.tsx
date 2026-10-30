"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { NavBar } from "@/components/layout/NavBar";
import { AppPageShell } from "@/components/layout/AppPageShell";

type GoalOut = {
  probability?: number | null;
  p05?: number | null;
  p95?: number | null;
  caption?: string;
  data_status?: string;
};

export default function GoalsPage() {
  const [amount, setAmount] = useState("3000000");
  const [date, setDate] = useState("2030-12-31");
  const [contrib, setContrib] = useState("0");
  const [data, setData] = useState<GoalOut | null>(null);

  const run = useCallback(async () => {
    const token = typeof window !== "undefined" ? localStorage.getItem("access_token") : null;
    const res = await fetch("/api/v1/goals", {
      method: "POST",
      credentials: "include",
      headers: {
        "Content-Type": "application/json",
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: JSON.stringify({
        target_amount: Number(amount),
        target_date: date,
        monthly_contrib: Number(contrib),
        mode: "paper",
      }),
    });
    if (!res.ok) {
      setData(null);
      return;
    }
    setData((await res.json()) as GoalOut);
  }, [amount, date, contrib]);

  useEffect(() => {
    void run();
  }, [run]);

  const p = data?.probability;
  return (
    <div className="min-h-screen bg-cockpit-bg text-qa-text">
      <NavBar activeTab="portfolio-risk" />
      <AppPageShell title="Цель">
        <div className="cockpit-panel p-4 space-y-3" data-testid="k5-goals">
          <label className="text-xs flex flex-col gap-1">
            Сумма, ₽
            <input className="bg-transparent border px-2 py-1" value={amount} onChange={(e) => setAmount(e.target.value)} data-testid="k5-amount" />
          </label>
          <label className="text-xs flex flex-col gap-1">
            Дата
            <input className="bg-transparent border px-2 py-1" value={date} onChange={(e) => setDate(e.target.value)} data-testid="k5-date" />
          </label>
          <label className="text-xs flex flex-col gap-1">
            Пополнение в месяц, ₽
            <input className="bg-transparent border px-2 py-1" value={contrib} onChange={(e) => setContrib(e.target.value)} data-testid="k5-contrib" />
          </label>
          <button type="button" className="border px-3 py-1 text-xs" data-testid="k5-calc" onClick={() => void run()}>
            Пересчитать
          </button>
          <p data-testid="k5-prob">
            Вероятность: {p == null ? "нет данных" : `${(p * 100).toFixed(0)}%`}
          </p>
          <p className="text-xs" data-testid="k5-caption">
            {data?.caption || "расчёт по прошлым данным, не обещание результата"}
          </p>
          <Link className="underline text-xs" href="/methodology/goals">
            Как это считается
          </Link>
        </div>
      </AppPageShell>
    </div>
  );
}
