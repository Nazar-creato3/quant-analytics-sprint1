"use client";

import Link from "next/link";
import { clsx } from "clsx";
import { Check, MessageSquare, X, Loader2 } from "lucide-react";

export function DealIntentActionBar({
  dealIntentId,
  label,
  busy,
  compact = false,
  onApprove,
  onReject,
}: {
  dealIntentId: string;
  label?: string;
  busy?: boolean;
  compact?: boolean;
  onApprove: (id: string) => void;
  onReject: (id: string) => void;
}) {
  const btn = compact ? "py-2 text-xs" : "py-2.5 text-sm";

  return (
    <div className={clsx("flex flex-col gap-1.5", compact ? "mt-2" : "mt-3")}>
      {label && (
        <p className="text-[10px] uppercase tracking-wide text-terminal-accent font-semibold">{label}</p>
      )}
      <div className="flex gap-2">
        <button
          type="button"
          title="Одобрить deal intent"
          onClick={() => onApprove(dealIntentId)}
          disabled={busy}
          className={clsx(
            "flex-1 flex items-center justify-center gap-1.5 font-bold btn-success",
            "disabled:opacity-50 disabled:cursor-not-allowed",
            btn,
          )}
        >
          {busy ? <Loader2 size={14} className="animate-spin" /> : <Check size={14} strokeWidth={2.5} />}
          Одобрить
        </button>
        <button
          type="button"
          title="Отклонить deal intent"
          onClick={() => onReject(dealIntentId)}
          disabled={busy}
          className={clsx(
            "flex-1 flex items-center justify-center gap-1.5 font-bold btn-danger-solid",
            "disabled:opacity-50 disabled:cursor-not-allowed",
            btn,
          )}
        >
          {busy ? <Loader2 size={14} className="animate-spin" /> : <X size={14} strokeWidth={2.5} />}
          Отклонить
        </button>
      </div>
      <Link
        href={`/chat?deal_intent=${dealIntentId}`}
        className={clsx(
          "inline-flex items-center justify-center gap-1.5 rounded-md font-semibold border border-terminal-accent/50",
          "text-terminal-accent bg-[var(--qa-active)] hover:bg-[var(--qa-active)] text-xs py-2",
        )}
      >
        <MessageSquare size={14} />
        Обсудить
      </Link>
    </div>
  );
}
