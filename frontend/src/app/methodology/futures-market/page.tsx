"use client";

import Link from "next/link";
import { NavBar } from "@/components/layout/NavBar";
import { AppPageShell } from "@/components/layout/AppPageShell";

export default function FuturesMarketMethodPage() {
  return (
    <div className="min-h-screen bg-cockpit-bg text-qa-text">
      <NavBar activeTab="portfolio-risk" />
      <AppPageShell title="Методика: рынок фьючерса">
        <p className="text-sm">
          Профиль объёма, дельта, FUTOI и фандинг — факты по сделкам и открытым позициям. Без направления.
        </p>
        <Link className="underline text-xs" href="/futures">
          К описанию
        </Link>
      </AppPageShell>
    </div>
  );
}
