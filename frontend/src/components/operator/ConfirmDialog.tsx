"use client";

import { clsx } from "clsx";
import { AlertTriangle, Loader2 } from "lucide-react";

export function ConfirmDialog({
  open,
  title,
  message,
  confirmLabel = "Да",
  cancelLabel = "Отмена",
  variant = "danger",
  loading = false,
  onConfirm,
  onCancel,
}: {
  open: boolean;
  title: string;
  message: string;
  confirmLabel?: string;
  cancelLabel?: string;
  variant?: "danger" | "caution";
  loading?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  if (!open) return null;

  return (
    <div className="modal-overlay">
      <button
        type="button"
        className="modal-backdrop"
        aria-label="Закрыть"
        onClick={onCancel}
      />
      <div role="dialog" aria-modal="true" className="modal-panel max-w-md">
        <div className="flex items-start gap-3 mb-3">
          <AlertTriangle
            size={18}
            className={clsx(
              "shrink-0 mt-0.5",
              variant === "danger" ? "text-terminal-down" : "text-terminal-accent",
            )}
          />
          <div>
            <h3 className="text-sm font-bold text-qa-text">{title}</h3>
            <p className="text-xs text-qa-text mt-1.5 leading-relaxed">{message}</p>
          </div>
        </div>
        <div className="flex justify-end gap-2">
          <button
            type="button"
            onClick={onCancel}
            disabled={loading}
            className="btn-secondary px-3 py-1.5 text-xs disabled:opacity-50"
          >
            {cancelLabel}
          </button>
          <button
            type="button"
            onClick={onConfirm}
            disabled={loading}
            className={clsx(
              "inline-flex items-center gap-1.5 px-3 py-1.5 rounded text-xs font-bold uppercase tracking-wide disabled:opacity-50 transition-colors duration-200",
              variant === "danger"
                ? "bg-qa-danger-bg text-terminal-down border border-terminal-down/40 hover:bg-qa-danger-bg"
                : "bg-[var(--qa-active)] text-terminal-accent border border-terminal-accent/40 hover:bg-[var(--qa-active)]",
            )}
          >
            {loading && <Loader2 size={12} className="animate-spin" />}
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
