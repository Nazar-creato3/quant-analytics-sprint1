"use client";

import { useEffect, useState } from "react";
import { lane2Get } from "@/lib/lane2-fetch";
import { betaAdminLines } from "@/lib/beta-admin";

export function BetaAdminCard() {
  const [lines, setLines] = useState(betaAdminLines());
  useEffect(() => {
    void lane2Get("/admin/beta/health?actor_id=ui").then((row) => {
      const missing = "нет данных";
      setLines([
        "Админка беты",
        "Роли: основатель, поддержка, аналитик",
        "Без второго фактора действие отклоняется",
        `Секрет: ${String(row.secret ?? missing)}`,
        `Лимит мест: ${String(row.seats ?? missing)}`,
        "Live и флаги юриста не включаются",
      ]);
    });
  }, []);
  return (
    <section aria-labelledby="beta-admin-title" className="bg-white p-4 text-neutral-800">
      <h1 id="beta-admin-title" className="text-lg font-medium">
        {lines[0]}
      </h1>
      <ul className="mt-2 list-disc pl-5 text-sm text-neutral-700">
        {lines.slice(1).map((line) => (
          <li key={line}>{line}</li>
        ))}
      </ul>
    </section>
  );
}
