"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { NavBar } from "@/components/layout/NavBar";
import { AppPageShell } from "@/components/layout/AppPageShell";
import { DataState } from "@/components/shared/DataState";
import { forecastApi } from "@/lib/api";
import { useProductContext } from "@/contexts/ProductContext";

export default function NotificationsPage() {
  const { activeAccount } = useProductContext();
  const [filter, setFilter] = useState("");
  const q = useQuery({
    queryKey: ["notifications", activeAccount, filter],
    queryFn: () => forecastApi.notifications(activeAccount, filter || undefined),
  });
  const items = q.data?.items || [];

  return (
    <div className="min-h-screen bg-cockpit-bg text-qa-text flex flex-col operator-shell">
      <NavBar />
      <AppPageShell title="Уведомления" description="Каналы и тихие часы. Бот только информирует.">
        <div className="space-y-3" data-testid="notify-center">
          <input className="w-full rounded border border-qa-border bg-transparent px-2 py-1 text-sm" placeholder="Фильтр типа" value={filter} onChange={(e) => setFilter(e.target.value)} />
          <DataState loading={q.isLoading} error={q.isError} empty={!items.length}>
            <ul className="space-y-2">
              {items.map((row) => (
                <li key={row.id} className="rounded border border-qa-border p-2 text-sm">
                  <p className="text-xs text-qa-muted">{row.event_name}</p>
                  <p>{row.text}</p>
                  <Link className="underline text-terminal-accent text-xs" href={row.href || "/portfolio"}>
                    Открыть
                  </Link>
                </li>
              ))}
            </ul>
          </DataState>
        </div>
      </AppPageShell>
    </div>
  );
}
