"use client";

import Link from "next/link";
import { NavBar } from "@/components/layout/NavBar";
import { AppPageShell } from "@/components/layout/AppPageShell";

export default function GoalsMethodPage() {
  return (
    <div className="min-h-screen bg-cockpit-bg text-qa-text">
      <NavBar activeTab="portfolio-risk" />
      <AppPageShell title="Методика: цель">
        <p className="text-sm">
          Bootstrap по прошлым дневным доходностям и интервал MAPIE. Не обещание результата.
        </p>
        <Link className="underline text-xs" href="/goals">
          К расчёту
        </Link>
      </AppPageShell>
    </div>
  );
}
