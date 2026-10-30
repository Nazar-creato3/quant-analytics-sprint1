"use client";

import { clsx } from "clsx";

export const BUCKET_LABELS: Record<string, string> = {
  paying: "Платит",
  full: "Полный доступ",
  trial: "Пробный период",
  blocked: "Заблокирован",
};

export type AdmissionActionRow = {
  id: string;
  contact_name?: string | null;
  contact_email: string;
  capital_range?: string | null;
  status: string;
  source: string;
  created_at: string;
  display_bucket?: string;
  is_admin?: boolean;
};

export function AdmissionActionButtons({
  row,
  disabled,
  onFullAccess,
  onAdmin,
  onRevokeAdmin,
  onSuspend,
}: {
  row: AdmissionActionRow;
  disabled?: boolean;
  onFullAccess: () => void;
  onAdmin: () => void;
  onRevokeAdmin: () => void;
  onSuspend: () => void;
}) {
  const bucket = row.display_bucket || "trial";
  const fullDone = bucket === "full" || bucket === "paying";
  const blocked = bucket === "blocked";

  return (
    <div className="flex flex-col gap-1 min-w-[9.5rem]">
      <button
        type="button"
        className="btn-primary text-[10px] px-2 py-1 disabled:opacity-40"
        disabled={disabled || (fullDone && !blocked)}
        onClick={onFullAccess}
      >
        Выдать полный доступ
      </button>
      <button
        type="button"
        className="btn-secondary text-[10px] px-2 py-1 disabled:opacity-40"
        disabled={disabled || row.is_admin}
        onClick={onAdmin}
      >
        Выдать права админа
      </button>
      <button
        type="button"
        className="btn-secondary text-[10px] px-2 py-1 disabled:opacity-40"
        disabled={disabled || !row.is_admin}
        onClick={onRevokeAdmin}
      >
        Отозвать права админа
      </button>
      <button
        type="button"
        className={clsx(
          "text-[10px] px-2 py-1 rounded border disabled:opacity-40",
          "border-terminal-down/50 text-terminal-down hover:bg-qa-danger-bg/30",
        )}
        disabled={disabled || blocked}
        onClick={onSuspend}
      >
        Приостановить полный доступ
      </button>
    </div>
  );
}
