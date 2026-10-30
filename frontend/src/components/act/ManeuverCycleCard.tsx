"use client";

import { useState } from "react";
import {
  REJECT_REASON_OPTIONS,
  costLabel,
  deadlineLabel,
  impactLines,
  statusLabel,
  type ManeuverCard,
} from "@/lib/maneuver-cycle";

type Props = {
  item: ManeuverCard;
  busy?: boolean;
  onView: () => void;
  onEdit: (qty: string) => void;
  onApprove: () => void;
  onReject: (reason: string, note: string) => void;
  onSend: () => void;
  onExecute: () => void;
  onClose: () => void;
};

export function ManeuverCycleCard({
  item,
  busy,
  onView,
  onEdit,
  onApprove,
  onReject,
  onSend,
  onExecute,
  onClose,
}: Props) {
  const [qty, setQty] = useState(item.qty || "");
  const [confirmed, setConfirmed] = useState(false);
  const [reason, setReason] = useState("size");
  const [note, setNote] = useState("");
  const titleId = `maneuver-${item.id || "card"}`;
  const status = item.status || "";

  return (
    <article className="border border-cockpit-border p-3 space-y-2" aria-labelledby={titleId} data-testid="maneuver-card">
      <h3 id={titleId} className="text-sm">
        Манёвр · {statusLabel(status)}
        {item.version ? ` · версия ${item.version}` : ""}
      </h3>
      <p className="text-sm">{item.rationale || "нет данных"}</p>
      <p className="text-xs text-qa-muted">Влияние: {impactLines(item).join("; ")}</p>
      <p className="text-xs text-qa-muted">Издержки: {costLabel(item)}</p>
      <p className="text-xs text-qa-muted">Срок: {deadlineLabel(item)}</p>
      {(item.orders || []).map((order) => (
        <p key={`${order.ticker}-${order.side}`} className="text-xs text-qa-muted">
          {order.ticker} {order.side} {order.qty} @ {order.price} ({order.price_source}, {order.license_tag})
        </p>
      ))}
      {(item.diff_vs_original || []).length > 0 ? (
        <div className="text-xs">
          <p>Отличие от исходного предложения</p>
          {item.diff_vs_original?.map((row) => (
            <p key={`${row.field}-${row.before}`}>
              {row.field}: {row.before} → {row.after}
            </p>
          ))}
        </div>
      ) : null}
      {item.send_block ? <p className="text-xs">Отправка: {item.send_block}</p> : null}
      <div className="flex flex-wrap gap-3 items-end">
        {status === "proposed" ? (
          <button type="button" className="text-xs underline text-terminal-accent" disabled={busy} onClick={onView}>
            Отметить просмотр
          </button>
        ) : null}
        {status === "viewed" || status === "edited" ? (
          <>
            <label className="text-xs text-qa-muted" htmlFor={`qty-${item.id}`}>
              Количество
              <input
                id={`qty-${item.id}`}
                className="ml-2 bg-transparent border border-cockpit-border px-1"
                value={qty}
                onChange={(event) => setQty(event.target.value)}
              />
            </label>
            <button type="button" className="text-xs underline text-terminal-accent" disabled={busy} onClick={() => onEdit(qty)}>
              Сохранить правку
            </button>
            <label className="text-xs text-qa-muted" htmlFor={`confirm-${item.id}`}>
              <input
                id={`confirm-${item.id}`}
                type="checkbox"
                className="mr-1"
                checked={confirmed}
                onChange={(event) => setConfirmed(event.target.checked)}
              />
              Подтверждаю одобрение
            </label>
            <button
              type="button"
              className="text-xs underline text-terminal-accent"
              disabled={busy || !confirmed}
              onClick={onApprove}
            >
              Одобрить
            </button>
            <label className="text-xs text-qa-muted" htmlFor={`reason-${item.id}`}>
              Причина отклонения
              <select
                id={`reason-${item.id}`}
                className="ml-2 bg-cockpit-bg border border-cockpit-border"
                value={reason}
                onChange={(event) => setReason(event.target.value)}
              >
                {REJECT_REASON_OPTIONS.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
            </label>
            <label className="text-xs text-qa-muted" htmlFor={`note-${item.id}`}>
              Комментарий
              <input
                id={`note-${item.id}`}
                className="ml-2 bg-transparent border border-cockpit-border px-1"
                value={note}
                onChange={(event) => setNote(event.target.value)}
              />
            </label>
            <button
              type="button"
              className="text-xs underline text-terminal-accent"
              disabled={busy}
              onClick={() => onReject(reason, note)}
            >
              Отклонить
            </button>
          </>
        ) : null}
        {status === "approved" ? (
          <button type="button" className="text-xs underline text-terminal-accent" disabled={busy} onClick={onSend}>
            Отправить
          </button>
        ) : null}
        {status === "sent" || status === "executed_partial" ? (
          <button type="button" className="text-xs underline text-terminal-accent" disabled={busy} onClick={onExecute}>
            Исполнить на бумаге
          </button>
        ) : null}
        {status === "executed_partial" || status === "executed_full" || status === "executed_paper" ? (
          <button type="button" className="text-xs underline text-terminal-accent" disabled={busy} onClick={onClose}>
            Закрыть
          </button>
        ) : null}
      </div>
    </article>
  );
}
