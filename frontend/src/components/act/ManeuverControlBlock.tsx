"use client";

import { controlLines, type ControlRow } from "@/lib/maneuver-control";

export function ManeuverControlBlock({
  status,
  items,
}: {
  status?: string;
  items?: ControlRow[];
}) {
  if (status === "off") {
    return <p className="text-xs text-qa-muted">Контроль манёвров выключен.</p>;
  }
  if (!items || items.length === 0) {
    return (
      <section aria-labelledby="maneuver-control-title" className="text-xs text-qa-muted">
        <h2 id="maneuver-control-title">Контроль манёвров</h2>
        <p>нет данных</p>
      </section>
    );
  }
  return (
    <section aria-labelledby="maneuver-control-title" className="text-xs space-y-1">
      <h2 id="maneuver-control-title">Контроль манёвров</h2>
      <ul>
        {items.map((row) => (
          <li key={String(row.maneuver_id)}>{controlLines(row).join(" · ")}</li>
        ))}
      </ul>
    </section>
  );
}
