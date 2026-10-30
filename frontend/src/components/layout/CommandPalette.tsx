"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { forecastApi } from "@/lib/api";

export function CommandPalette() {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  const [items, setItems] = useState<Array<{ label: string; href: string }>>([]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setOpen((v) => !v);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  useEffect(() => {
    if (!open) return;
    forecastApi.qaSearch(q).then((res) => setItems(res.items || [])).catch(() => setItems([]));
  }, [open, q]);

  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 bg-black/40 flex items-start justify-center pt-24" data-testid="command-palette">
      <div className="w-full max-w-lg rounded-xl border border-qa-border bg-cockpit-bg p-3 space-y-2">
        <input
          autoFocus
          className="w-full rounded border border-qa-border bg-transparent px-2 py-1 text-sm"
          placeholder="Разделы и действия"
          value={q}
          onChange={(e) => setQ(e.target.value)}
        />
        <ul className="text-sm space-y-1">
          {items.length ? items.map((row) => (
            <li key={`${row.href}-${row.label}`}>
              <button type="button" className="underline text-terminal-accent" onClick={() => { router.push(row.href); setOpen(false); }}>
                {row.label}
              </button>
            </li>
          )) : <li className="text-qa-muted">нет данных</li>}
        </ul>
      </div>
    </div>
  );
}
