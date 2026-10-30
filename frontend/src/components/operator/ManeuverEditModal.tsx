"use client";

import Link from "next/link";
import { clsx } from "clsx";
import { X } from "lucide-react";
import type { Maneuver } from "@/types";

export function ManeuverEditModal({
  maneuver,
  onClose,
}: {
  maneuver: Maneuver;
  onClose: () => void;
}) {
  return (
    <div className="fixed inset-0 z-[100] flex items-center justify-center p-4">
      <button type="button" className="absolute inset-0 bg-black/75" aria-label="Закрыть" onClick={onClose} />
      <div className="relative w-full max-w-md rounded-lg border border-cockpit-border-strong bg-cockpit-panel">
        <div className="flex items-center justify-between px-4 py-3 border-b border-cockpit-border">
          <h2 className="text-sm font-bold text-white">
            Изменить · {maneuver.ticker}
          </h2>
          <button type="button" onClick={onClose} className="text-qa-muted hover:text-qa-text">
            <X size={16} />
          </button>
        </div>
        <div className="p-4 space-y-3 text-xs text-qa-text">
          <p>
            Перед одобрением проверьте зону входа, SL/TP и размер. Полное редактирование параметров —
            в Asset Cockpit и Strategy Composer.
          </p>
          <dl className="space-y-2">
            <div className="flex justify-between gap-2">
              <dt className="text-qa-muted">Стратегия</dt>
              <dd className="font-mono text-white">{maneuver.strategy_type}</dd>
            </div>
            <div className="flex justify-between gap-2">
              <dt className="text-qa-muted">Размер</dt>
              <dd className="tabular-nums">${maneuver.position_size_usd.toLocaleString()}</dd>
            </div>
            <div className="flex justify-between gap-2">
              <dt className="text-qa-muted">SL / TP</dt>
              <dd className="tabular-nums">
                {maneuver.stop_loss?.toFixed(2) ?? "—"} / {maneuver.take_profit?.toFixed(2) ?? "—"}
              </dd>
            </div>
          </dl>
          <Link
            href={`/cockpit/${encodeURIComponent(maneuver.ticker)}`}
            className={clsx(
              "block w-full text-center py-2 rounded text-xs font-semibold",
              "bg-[var(--qa-active)] text-terminal-accent border border-terminal-accent/50 hover:bg-[var(--qa-active)]",
            )}
          >
            Открыть Cockpit для детального анализа
          </Link>
        </div>
      </div>
    </div>
  );
}
