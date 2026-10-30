"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useProductContext } from "@/contexts/ProductContext";

type Signal = {
  signal_id: string;
  module_label: string;
  figure: string;
  label: string;
  why: string;
  if_idle: string;
  confidence: string;
  href: string;
  methodology: string;
  source: string;
  as_of?: string | null;
  journal_id?: string;
};

type Payload = {
  caption?: string;
  data_status?: string;
  reason?: string | null;
  screen?: Signal[];
  missing?: { module: string; reason: string }[];
  journal?: { id: string; signal_id: string }[];
};

const EMPTY = "нет данных";

export function BrainNow() {
  const { mode } = useProductContext();
  const [state, setState] = useState<"loading" | "error" | "ready" | "off">("loading");
  const [data, setData] = useState<Payload | null>(null);
  const [note, setNote] = useState("");

  const load = useCallback(async () => {
    setState("loading");
    const token = typeof window !== "undefined" ? localStorage.getItem("access_token") : null;
    try {
      const res = await fetch(`/api/v1/decision-core?mode=${mode}`, {
        credentials: "include",
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      });
      if (res.status === 404) {
        // The summary is switched off on the server (qa_decision_core): hide the block
        // instead of showing a bare "нет данных" on the home page.
        setData(null);
        setState("off");
        return;
      }
      if (!res.ok) {
        setData(null);
        setState("error");
        return;
      }
      setData((await res.json()) as Payload);
      setState("ready");
    } catch {
      setData(null);
      setState("error");
    }
  }, [mode]);

  useEffect(() => {
    void load();
  }, [load]);

  const act = async (entryId: string, action: "opened" | "noted" | "dismissed") => {
    const token = localStorage.getItem("access_token");
    const res = await fetch(`/api/v1/decision-core/journal/${entryId}/action`, {
      method: "POST",
      credentials: "include",
      headers: {
        "Content-Type": "application/json",
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: JSON.stringify({ action }),
    });
    setNote(res.ok ? "Записано в журнал" : EMPTY);
  };

  const screen = (data?.screen || []).slice(0, 5);
  const journalBySignal = new Map((data?.journal || []).map((row) => [row.signal_id, row.id]));

  if (state === "off") return null;

  return (
    <section className="cockpit-panel mx-2 mt-2 p-3 space-y-2 shrink-0" data-testid="brain-now">
      <h2 className="text-sm font-semibold">Главное сейчас</h2>
      <p className="text-xs" data-testid="brain-caption">
        {data?.caption || "Сводка расчётов по вашим данным. Это не индивидуальная инвестиционная рекомендация. Решение принимаете вы."}
      </p>
      {state === "loading" ? <p data-testid="brain-status">Считаем</p> : null}
      {state === "error" ? <p data-testid="brain-status">Сводка временно недоступна — обновите страницу.</p> : null}
      {state === "ready" && screen.length === 0 ? (
        <p data-testid="brain-status">
          {data?.reason || "Сводка появится, когда в портфеле будут позиции: подключите счёт брокера или загрузите пример портфеля."}
        </p>
      ) : null}
      {state === "ready"
        ? screen.map((row) => {
            const entryId = journalBySignal.get(row.signal_id);
            return (
              <article key={row.signal_id} className="border border-white/10 p-2 text-xs space-y-1" data-testid={`brain-signal-${row.signal_id}`}>
                <p>{row.why}</p>
                <p>
                  {row.label}: {row.figure}. Уверенность: {row.confidence}.
                  {row.as_of ? ` Дата данных: ${row.as_of}.` : ""} Источник: {row.source}.
                </p>
                <p>{row.if_idle}</p>
                <p className="flex gap-3">
                  <Link className="underline inline-flex items-center min-h-6 min-w-6" href={row.href}>
                    Открыть модуль
                  </Link>
                  <Link className="underline inline-flex items-center min-h-6 min-w-6" href={row.methodology}>
                    Как это считается
                  </Link>
                </p>
                {entryId ? (
                  <p className="flex gap-2">
                    <button type="button" className="underline min-h-6 min-w-6 px-2" onClick={() => void act(entryId, "opened")}>
                      Открыл
                    </button>
                    <button type="button" className="underline min-h-6 min-w-6 px-2" onClick={() => void act(entryId, "noted")}>
                      Отметил
                    </button>
                    <button type="button" className="underline min-h-6 min-w-6 px-2" onClick={() => void act(entryId, "dismissed")}>
                      Скрыл
                    </button>
                  </p>
                ) : null}
              </article>
            );
          })
        : null}
      {state === "ready" && (data?.missing || []).length > 0 ? (
        <p className="text-xs" data-testid="brain-missing">
          Нет цифры: {(data?.missing || []).map((row) => row.module).join(", ")}
        </p>
      ) : null}
      {note ? <p data-testid="brain-journal">{note}</p> : null}
    </section>
  );
}
