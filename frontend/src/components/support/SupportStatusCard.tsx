"use client";

import { useEffect, useState } from "react";
import { lane2Get } from "@/lib/lane2-fetch";

export function SupportStatusCard() {
  const [issues, setIssues] = useState("нет данных");
  useEffect(() => {
    void lane2Get("/support/status").then((row) => {
      setIssues(String(row.known_issues ?? "нет данных"));
    });
  }, []);
  return (
    <main className="mx-auto max-w-3xl p-4">
      <h1 className="text-lg font-medium">Состояние сервиса</h1>
      <p className="mt-2 text-sm text-qa-muted">Известные проблемы: {issues}</p>
    </main>
  );
}
