"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { clsx } from "clsx";
import { Check, X, Pencil, Ban, Loader2 } from "lucide-react";
import { isManeuverCancellable } from "@/lib/maneuvers";
import { isPendingApproval } from "@/lib/approval";
import type { ManeuverApprovalOptions } from "@/types";
import { formatDurationPresets } from "@/lib/duration-i18n";
import { ManeuverIdeaButton } from "./ManeuverIdeaDialog";
import type { Maneuver } from "@/types";

const DURATION_PRESETS = formatDurationPresets("ru");

export function ManeuverActionBar({
  maneuverId,
  ticker,
  status,
  busy,
  compact = false,
  initialHorizon,
  maneuver,
  onApprove,
  onReject,
  onEdit,
  onCancel,
}: {
  maneuverId: string;
  ticker: string;
  status?: string;
  busy?: boolean;
  compact?: boolean;
  initialHorizon?: string | null;
  maneuver?: Maneuver | null;
  onApprove: (id: string, options?: ManeuverApprovalOptions) => void;
  onReject: (id: string) => void;
  onEdit?: (id: string) => void;
  onCancel: (id: string) => void;
}) {
  const pathname = usePathname();
  const cockpitSymbol = pathname?.match(/^\/cockpit\/([^/]+)/)?.[1];
  const onSameCockpitPage =
    cockpitSymbol != null && decodeURIComponent(cockpitSymbol).toUpperCase() === ticker.toUpperCase();

  const showApproval = isPendingApproval(status);
  const canClose = isManeuverCancellable(status) && !showApproval;
  const [durationDraft, setDurationDraft] = useState(initialHorizon || "7 дней");
  const [expiryDraft, setExpiryDraft] = useState("");

  useEffect(() => {
    setDurationDraft(initialHorizon || "7 дней");
    setExpiryDraft("");
  }, [initialHorizon, maneuverId]);

  const approvalOptions = (): ManeuverApprovalOptions => ({
    time_horizon: durationDraft.trim() || undefined,
    expiry_at: expiryDraft ? new Date(expiryDraft).toISOString() : undefined,
  });

  const btn = compact ? "py-1.5 text-[10px]" : "py-2 text-xs";
  const linkBtn = clsx(
    "inline-flex items-center justify-center gap-1 rounded-md font-semibold shrink-0",
    "text-terminal-accent border border-terminal-accent/40 hover:bg-[var(--qa-active)]",
    compact ? "px-2 py-1.5 text-[10px]" : "px-3 py-2 text-xs",
  );

  return (
    <div className={clsx("flex flex-col gap-1.5", compact ? "mt-1.5" : "mt-3")}>
      <div className="flex flex-wrap gap-1 min-w-0">
        {showApproval && (
          <>
            <button
              type="button"
              title="Записать одобрение"
              onClick={() => onApprove(maneuverId, approvalOptions())}
              disabled={busy}
              className={clsx(
                "flex-1 min-w-[4.5rem] flex items-center justify-center gap-1 font-bold btn-success",
                "disabled:opacity-50 disabled:cursor-not-allowed",
                btn,
              )}
            >
              {busy ? <Loader2 size={12} className="animate-spin" /> : <Check size={12} strokeWidth={2.5} />}
              Одобрить
            </button>
            <button
              type="button"
              title="Отклонить — идея не пойдёт дальше"
              onClick={() => onReject(maneuverId)}
              disabled={busy}
              className={clsx(
                "flex-1 min-w-[4.5rem] flex items-center justify-center gap-1 font-bold btn-danger-solid",
                "disabled:opacity-50 disabled:cursor-not-allowed",
                btn,
              )}
            >
              {busy ? <Loader2 size={12} className="animate-spin" /> : <X size={12} strokeWidth={2.5} />}
              Отклонить
            </button>
          </>
        )}
        {!onSameCockpitPage && (
          <Link href={`/cockpit/${encodeURIComponent(ticker)}`} className={linkBtn}>
            Карточка
          </Link>
        )}
        {maneuver ? <ManeuverIdeaButton m={maneuver} /> : null}
      </div>

      {showApproval && (
        <div className="rounded-md border border-terminal-accent/25 bg-terminal-accent/5 p-2">
          <div className="flex items-center justify-between gap-2 mb-1.5">
            <span className="text-[9px] uppercase tracking-wide text-qa-muted">Срок идеи</span>
            <span className="text-[9px] text-terminal-accent tabular-nums">
              {expiryDraft ? "точное время" : durationDraft || "срок"}
            </span>
          </div>
          <div className="flex flex-wrap gap-1 mb-1.5">
            {DURATION_PRESETS.map((preset) => (
              <button
                key={preset.key}
                type="button"
                onClick={() => {
                  setDurationDraft(preset.api);
                  setExpiryDraft("");
                }}
                disabled={busy}
                className={clsx(
                  "px-1.5 py-0.5 rounded border text-[9px]",
                  durationDraft === preset.api && !expiryDraft
                    ? "border-terminal-accent/60 text-terminal-accent bg-[var(--qa-active)]"
                    : "border-qa-border text-qa-muted bg-qa-panel-secondary",
                )}
              >
                {preset.label}
              </button>
            ))}
          </div>
          <div className="grid grid-cols-2 gap-1.5">
            <input
              value={durationDraft}
              onChange={(e) => setDurationDraft(e.target.value)}
              disabled={busy}
              placeholder="7 дней"
              className="min-w-0 rounded border border-qa-border bg-qa-panel px-1.5 py-1 text-[10px] text-qa-text"
            />
            <input
              type="datetime-local"
              value={expiryDraft}
              onChange={(e) => setExpiryDraft(e.target.value)}
              disabled={busy}
              title="Точное время закрытия, если нужно"
              className="min-w-0 rounded border border-qa-border bg-qa-panel px-1.5 py-1 text-[10px] text-qa-text"
            />
          </div>
        </div>
      )}

      {(showApproval && onEdit) || canClose ? (
        <div className="flex flex-wrap gap-1.5">
          {showApproval && onEdit && (
            <button
              type="button"
              title="Изменить параметры"
              onClick={() => onEdit(maneuverId)}
              disabled={busy}
              className={clsx(
                "flex items-center justify-center gap-1 px-2 rounded-md font-semibold",
                "bg-[var(--qa-active)] text-terminal-text border border-terminal-accent/50 hover:bg-[var(--qa-active)]",
                "disabled:opacity-50",
                compact ? "py-1 text-[10px]" : "py-1.5 text-xs",
              )}
            >
              <Pencil size={11} />
              Изменить
            </button>
          )}
          {canClose && (
            <button
              type="button"
              title="Закрыть идею или бумажную позицию"
              onClick={() => onCancel(maneuverId)}
              disabled={busy}
              className={clsx(
                "flex-1 flex items-center justify-center gap-1 rounded-md font-semibold",
                "bg-qa-panel-secondary text-qa-text border border-qa-border-strong hover:bg-[var(--qa-hover)]",
                "disabled:opacity-50",
                compact ? "py-1 text-[10px]" : "py-1.5 text-xs",
              )}
            >
              {busy ? <Loader2 size={11} className="animate-spin" /> : <Ban size={11} />}
              Закрыть
            </button>
          )}
        </div>
      ) : null}
    </div>
  );
}
