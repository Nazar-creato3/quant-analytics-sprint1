"use client";

import { useQuery } from "@tanstack/react-query";
import { AlertTriangle } from "lucide-react";

async function fetchRisks() {
  const res = await fetch("/api/v1/tokenized-equities/content");
  if (!res.ok) throw new Error("Не удалось загрузить данные");
  return res.json();
}

interface Props {
  onAccept: () => void;
  onDismiss?: () => void;
}

export function TradingDisclosuresModal({ onAccept, onDismiss }: Props) {
  const { data } = useQuery({ queryKey: ["tokenized-equities-content"], queryFn: fetchRisks });
  const risks = data?.risks ?? [];

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4">
      <div className="card max-w-lg w-full p-6 space-y-4 max-h-[90vh] overflow-y-auto">
        <div className="flex items-center gap-2 text-amber-400">
          <AlertTriangle size={20} />
          <h2 className="font-semibold text-lg">Риски токенизированных акций</h2>
        </div>
        <p className="text-xs text-qa-muted">
          Перед подключением счёта прочитайте риски и подтвердите, что понимаете условия исполнения.
        </p>

        <ul className="space-y-3">
          {risks.map((r: { id: string; title: string; body: string }) => (
            <li key={r.id} className="text-sm">
              <p className="font-medium">{r.title}</p>
              <p className="text-xs text-qa-muted mt-1 leading-relaxed">{r.body}</p>
            </li>
          ))}
        </ul>

        <p className="text-xs text-qa-muted">
          Котировки для аналитики и исполнение заявок идут через площадки. Остатки и сделки зависят от выбранного счёта.
        </p>

        <div className="flex gap-2 pt-2">
          <button type="button" className="btn-primary flex-1 text-sm" onClick={onAccept}>
            Понятно, продолжить
          </button>
          {onDismiss && (
            <button type="button" className="btn-secondary text-sm" onClick={onDismiss}>
              Отмена
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

export function TradingDisclosuresInline() {
  const { data } = useQuery({ queryKey: ["tokenized-equities-content"], queryFn: fetchRisks });
  const risks = data?.risks ?? [];

  return (
    <details className="text-xs text-qa-muted border border-white/10 rounded-lg p-3">
      <summary className="cursor-pointer font-medium text-sm text-white/80">
        Риски токенизированных акций
      </summary>
      <ul className="mt-3 space-y-2 list-disc pl-4">
        {risks.map((r: { id: string; title: string; body: string }) => (
          <li key={r.id}>
            <strong>{r.title}.</strong> {r.body}
          </li>
        ))}
      </ul>
    </details>
  );
}
