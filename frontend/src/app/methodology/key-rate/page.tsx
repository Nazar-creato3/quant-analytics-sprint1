"use client";

import Link from "next/link";
import { NavBar } from "@/components/layout/NavBar";
import { AppPageShell } from "@/components/layout/AppPageShell";

export default function KeyRateMethodPage() {
  return (
    <div className="min-h-screen bg-cockpit-bg text-qa-text">
      <NavBar activeTab="factors" />
      <AppPageShell title="Методика: ставка ЦБ">
        <p className="text-sm">
          Формулы: docs/methodology/key-rate.md. Облигации — дюрация и выпуклость. Акции — бета
          фактора ставки. Подпись: по прошлой реакции рынка, не прогноз.
        </p>
        <Link className="underline text-xs" href="/portfolio?tab=risk">
          К расчёту
        </Link>
      </AppPageShell>
    </div>
  );
}
