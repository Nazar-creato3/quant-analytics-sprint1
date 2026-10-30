"use client";

import { statusLabelRu } from "@/lib/human-ru";

import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { clsx } from "clsx";
import { Loader2, XCircle, Pencil, Check } from "lucide-react";
import { toast } from "react-hot-toast";
import { ordersApi } from "@/lib/api";
import { extractErrorMessage } from "@/lib/errors";
import type { ManualOrder } from "@/types";

const STATUS_COLORS: Record<string, string> = {
  pending: "text-terminal-accent",
  submitted: "text-terminal-accent",
  partial: "text-qa-warning",
  watching: "text-qa-warning",
  filled: "text-terminal-up",
  cancelled: "text-qa-muted",
  rejected: "text-terminal-down",
};

const WORKING = new Set(["pending", "submitted", "watching", "partial"]);
const MODIFIABLE = new Set(["limit", "stop_limit"]);

interface ManualOrdersPanelProps {
  ticker?: string;
  pollMs?: number;
  className?: string;
}

export function ManualOrdersPanel({ ticker, pollMs = 5000, className }: ManualOrdersPanelProps) {
  const queryClient = useQueryClient();
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editPrice, setEditPrice] = useState("");
  const [editQty, setEditQty] = useState("");

  const { data: orders, isLoading } = useQuery({
    queryKey: ["manual-orders", ticker ?? "all"],
    queryFn: () => ordersApi.list(ticker ? { ticker } : undefined),
    refetchInterval: pollMs,
  });

  const cancelMutation = useMutation({
    mutationFn: (orderId: string) => ordersApi.cancel(orderId),
    onSuccess: () => {
      toast.success("Order cancelled");
      queryClient.invalidateQueries({ queryKey: ["manual-orders"] });
    },
    onError: (err) => toast.error(extractErrorMessage(err, "Не удалось отменить заявку")),
  });

  const modifyMutation = useMutation({
    mutationFn: ({ id, limit_price, quantity }: { id: string; limit_price?: number; quantity?: number }) =>
      ordersApi.modify(id, { limit_price, quantity }),
    onSuccess: () => {
      toast.success("Order updated");
      setEditingId(null);
      queryClient.invalidateQueries({ queryKey: ["manual-orders"] });
    },
    onError: (err) => toast.error(extractErrorMessage(err, "Modify failed")),
  });

  const rows = useMemo(() => orders ?? [], [orders]);
  const openRows = rows.filter((o) => WORKING.has(o.status));
  const historyRows = rows.filter((o) => !WORKING.has(o.status)).slice(0, 10);

  const startEdit = (o: ManualOrder) => {
    setEditingId(o.id);
    setEditPrice(o.limit_price != null ? String(o.limit_price) : "");
    setEditQty(String(o.quantity));
  };

  if (isLoading && !orders) {
    return (
      <div className="rounded-lg border border-qa-border bg-qa-panel p-4 text-xs text-qa-muted flex items-center gap-2">
        <Loader2 size={14} className="animate-spin" /> Загружаем заявки…
      </div>
    );
  }

  return (
    <div className={clsx("rounded-lg border border-qa-border bg-qa-panel p-4 flex flex-col min-h-0 max-h-[min(360px,40vh)]", className)}>
      <div className="flex items-center justify-between mb-3 shrink-0">
        <h3 className="text-sm font-semibold text-qa-text">Мои заявки</h3>
        <span className="text-[10px] uppercase text-qa-muted">
          {openRows.length} open · {rows.length} total
        </span>
      </div>

      {rows.length === 0 ? (
        <p className="text-xs text-qa-muted">Заявок пока нет.</p>
      ) : (
        <div className="flex-1 min-h-0 overflow-y-auto space-y-4">
          {openRows.length > 0 && (
            <OrderTable
              title="Активные"
              rows={openRows}
              editingId={editingId}
              editPrice={editPrice}
              editQty={editQty}
              onEditPrice={setEditPrice}
              onEditQty={setEditQty}
              onStartEdit={startEdit}
              onCancelEdit={() => setEditingId(null)}
              onSaveEdit={(id) => {
                const limit_price = parseFloat(editPrice);
                const quantity = parseFloat(editQty);
                modifyMutation.mutate({
                  id,
                  ...(Number.isFinite(limit_price) ? { limit_price } : {}),
                  ...(Number.isFinite(quantity) ? { quantity } : {}),
                });
              }}
              modifyBusy={modifyMutation.isPending}
              cancelBusy={cancelMutation.isPending}
              onCancelOrder={(id) => cancelMutation.mutate(id)}
            />
          )}
          {historyRows.length > 0 && (
            <OrderTable
              title="Недавние"
              rows={historyRows}
              readOnly
              editingId={null}
              editPrice=""
              editQty=""
              onEditPrice={() => undefined}
              onEditQty={() => undefined}
              onStartEdit={() => undefined}
              onCancelEdit={() => undefined}
              onSaveEdit={() => undefined}
              modifyBusy={false}
              cancelBusy={false}
              onCancelOrder={() => undefined}
            />
          )}
        </div>
      )}
    </div>
  );
}

function OrderTable({
  title,
  rows,
  readOnly,
  editingId,
  editPrice,
  editQty,
  onEditPrice,
  onEditQty,
  onStartEdit,
  onCancelEdit,
  onSaveEdit,
  modifyBusy,
  cancelBusy,
  onCancelOrder,
}: {
  title: string;
  rows: ManualOrder[];
  readOnly?: boolean;
  editingId: string | null;
  editPrice: string;
  editQty: string;
  onEditPrice: (v: string) => void;
  onEditQty: (v: string) => void;
  onStartEdit: (o: ManualOrder) => void;
  onCancelEdit: () => void;
  onSaveEdit: (id: string) => void;
  modifyBusy: boolean;
  cancelBusy: boolean;
  onCancelOrder: (id: string) => void;
}) {
  return (
    <div>
      <p className="text-[10px] uppercase text-qa-muted mb-1.5">{title}</p>
      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="text-qa-muted border-b border-qa-border">
              {["Бумага", "Сторона", "Тип", "Кол-во, шт.", "Цена", "Статус", ""].map((h) => (
                <th key={h || "actions"} className="py-1.5 text-left font-medium">
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((o) => {
              const editing = editingId === o.id;
              const canModify = !readOnly && WORKING.has(o.status) && MODIFIABLE.has(o.order_type);
              return (
                <tr key={o.id} className="border-b border-qa-border/50">
                  <td className="py-2 font-mono">{o.ticker}</td>
                  <td className={clsx("py-2 uppercase", o.side === "buy" ? "text-terminal-up" : "text-terminal-down")}>
                    {o.side}
                  </td>
                  <td className="py-2">{o.order_type.replace("_", "-")}</td>
                  <td className="py-2 tabular-nums">
                    {editing ? (
                      <input
                        type="number"
                        value={editQty}
                        onChange={(e) => onEditQty(e.target.value)}
                        className="w-20 bg-qa-panel-secondary border border-qa-border rounded px-1 py-0.5"
                      />
                    ) : (
                      o.quantity
                    )}
                  </td>
                  <td className="py-2 tabular-nums">
                    {editing ? (
                      <input
                        type="number"
                        value={editPrice}
                        onChange={(e) => onEditPrice(e.target.value)}
                        className="w-24 bg-qa-panel-secondary border border-qa-border rounded px-1 py-0.5"
                      />
                    ) : (
                      o.limit_price ?? "—"
                    )}
                  </td>
                  <td className={clsx("py-2 uppercase", STATUS_COLORS[o.status] || "text-qa-muted")}>
                    {statusLabelRu(o.status)}
                  </td>
                  <td className="py-2 text-right whitespace-nowrap">
                    {!readOnly && WORKING.has(o.status) && (
                      <div className="inline-flex items-center gap-1">
                        {editing ? (
                          <>
                            <button
                              type="button"
                              disabled={modifyBusy}
                              onClick={() => onSaveEdit(o.id)}
                              className="p-1 rounded hover:bg-[var(--qa-hover)] text-terminal-up"
                              title="Сохранить"
                            >
                              <Check size={12} />
                            </button>
                            <button
                              type="button"
                              onClick={onCancelEdit}
                              className="p-1 rounded hover:bg-[var(--qa-hover)] text-qa-muted"
                              title="Отменить изменения"
                            >
                              <XCircle size={12} />
                            </button>
                          </>
                        ) : (
                          <>
                            {canModify && (
                              <button
                                type="button"
                                onClick={() => onStartEdit(o)}
                                className="p-1 rounded hover:bg-[var(--qa-hover)] text-terminal-accent"
                                title="Изменить"
                              >
                                <Pencil size={12} />
                              </button>
                            )}
                            <button
                              type="button"
                              disabled={cancelBusy}
                              onClick={() => onCancelOrder(o.id)}
                              className="inline-flex items-center gap-1 px-2 py-0.5 rounded border border-qa-border hover:bg-[var(--qa-hover)] text-qa-muted"
                            >
                              <XCircle size={12} /> Отменить
                            </button>
                          </>
                        )}
                      </div>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
