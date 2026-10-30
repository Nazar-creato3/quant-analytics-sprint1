"use client";

import { useState } from "react";
import { Download, KeyRound, Trash2 } from "lucide-react";
import Link from "next/link";
import api, { authApi } from "@/lib/api";
import { subjectRightsLines } from "@/lib/subject-rights";

const BTN =
  "inline-flex items-center gap-1.5 rounded-md border border-cockpit-border px-3 py-1.5 text-xs " +
  "text-qa-text/90 transition-colors hover:border-terminal-accent/60 hover:text-terminal-accent disabled:opacity-50";

export function SubjectRightsCard() {
  const lines = subjectRightsLines();
  const [busy, setBusy] = useState<"export" | "delete" | null>(null);
  const [status, setStatus] = useState<string | null>(null);

  const exportData = async () => {
    setBusy("export");
    setStatus(null);
    try {
      const { data } = await api.get("/privacy/export");
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `quant-analytics-my-data-${new Date().toISOString().slice(0, 10)}.json`;
      a.click();
      URL.revokeObjectURL(url);
      setStatus("Файл с вашими данными скачан.");
    } catch {
      setStatus("Не удалось подготовить выгрузку. Попробуйте позже.");
    } finally {
      setBusy(null);
    }
  };

  const deleteAccount = async () => {
    const ok = window.confirm(
      "Удалить аккаунт? Портфели, история и настройки будут удалены без возможности восстановления.",
    );
    if (!ok) return;
    setBusy("delete");
    setStatus(null);
    try {
      const { data } = await api.post("/subject-rights/delete", {});
      if ((data as { status?: string })?.status === "rejected") {
        setStatus("Удаление сейчас недоступно. Напишите в поддержку.");
        return;
      }
      authApi.logout();
      window.location.href = "/login";
    } catch {
      setStatus("Не удалось удалить аккаунт. Напишите в поддержку.");
    } finally {
      setBusy(null);
    }
  };

  return (
    <section
      aria-labelledby="subject-rights-title"
      className="mt-4 rounded-lg border border-cockpit-border bg-cockpit-surface p-4"
      data-testid="subject-rights"
    >
      <h2 id="subject-rights-title" className="text-sm font-semibold text-qa-text">
        {lines[0]}
      </h2>
      <ul className="mt-2 space-y-1 text-xs text-qa-muted">
        {lines.slice(1).map((line) => (
          <li key={line}>· {line}</li>
        ))}
      </ul>
      <div className="mt-3 flex flex-wrap gap-2">
        <button type="button" className={BTN} onClick={exportData} disabled={busy !== null}>
          <Download size={13} aria-hidden />
          {busy === "export" ? "Готовим файл…" : "Скачать мои данные"}
        </button>
        <Link href="/settings" className={BTN}>
          <KeyRound size={13} aria-hidden />
          Ключи брокеров
        </Link>
        <button
          type="button"
          className={`${BTN} hover:border-terminal-down/60 hover:text-terminal-down`}
          onClick={deleteAccount}
          disabled={busy !== null}
        >
          <Trash2 size={13} aria-hidden />
          {busy === "delete" ? "Удаляем…" : "Удалить аккаунт"}
        </button>
      </div>
      {status ? (
        <p className="mt-2 text-xs text-qa-muted" role="status">
          {status}
        </p>
      ) : null}
    </section>
  );
}
