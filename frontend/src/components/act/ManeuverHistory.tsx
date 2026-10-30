"use client";

import { useState } from "react";
import { MANEUVER_STATUS_LABELS, filterByStatus, statusLabel, type ManeuverCard } from "@/lib/maneuver-cycle";

export function ManeuverHistory({ items }: { items: ManeuverCard[] }) {
  const [status, setStatus] = useState("");
  const shown = filterByStatus(items, status);
  return (
    <section className="cockpit-panel p-4 text-xs space-y-2" aria-labelledby="maneuver-history-title">
      <h2 id="maneuver-history-title" className="uppercase tracking-wide text-qa-muted">
        История манёвров
      </h2>
      <label htmlFor="maneuver-status-filter" className="text-qa-muted">
        Состояние
        <select
          id="maneuver-status-filter"
          className="ml-2 bg-cockpit-bg border border-cockpit-border"
          value={status}
          onChange={(event) => setStatus(event.target.value)}
        >
          <option value="">все</option>
          {Object.entries(MANEUVER_STATUS_LABELS).map(([value, label]) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </select>
      </label>
      {shown.length === 0 ? <p>нет данных</p> : null}
      <ul className="space-y-1">
        {shown.map((item) => (
          <li key={String(item.id)}>
            {statusLabel(item.status)} · {item.rationale || "нет данных"}
          </li>
        ))}
      </ul>
    </section>
  );
}
