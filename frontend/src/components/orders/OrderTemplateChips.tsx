"use client";

import { useMemo, useState } from "react";
import { clsx } from "clsx";
import {
  deleteOrderTemplate,
  listOrderTemplates,
  saveOrderTemplate,
  type OrderTemplate,
} from "@/lib/order-templates";

interface OrderTemplateChipsProps {
  ticker: string;
  orderType: string;
  sizePct: number;
  slDistancePct: number | null;
  tpDistancePct: number | null;
  tif?: string;
  postOnly?: boolean;
  onApply: (tpl: OrderTemplate) => void;
}

export function OrderTemplateChips({
  ticker,
  orderType,
  sizePct,
  slDistancePct,
  tpDistancePct,
  tif,
  postOnly,
  onApply,
}: OrderTemplateChipsProps) {
  const [items, setItems] = useState<OrderTemplate[]>(() => listOrderTemplates());
  const [saving, setSaving] = useState(false);
  const [name, setName] = useState("");

  const visible = useMemo(
    () => items.filter((t) => !t.ticker || t.ticker === ticker).slice(0, 8),
    [items, ticker],
  );

  const onSave = () => {
    const next = saveOrderTemplate({
      name: name.trim() || `${ticker} ${orderType} ${sizePct}%`,
      ticker,
      orderType,
      sizePct,
      slDistancePct,
      tpDistancePct,
      tif,
      postOnly,
    });
    setItems(next);
    setName("");
    setSaving(false);
  };

  return (
    <div className="space-y-1">
      <div className="flex flex-wrap gap-1 items-center">
        {visible.map((tpl) => (
          <button
            key={tpl.id}
            type="button"
            className="px-1.5 py-0.5 text-[10px] rounded-full border border-qa-border text-qa-muted hover:text-white hover:border-terminal-accent"
            onClick={() => onApply(tpl)}
            onContextMenu={(e) => {
              e.preventDefault();
              setItems(deleteOrderTemplate(tpl.id));
            }}
            title="Клик — применить (без отправки). ПКМ — удалить."
          >
            {tpl.name}
          </button>
        ))}
        {!saving ? (
          <button
            type="button"
            className="px-1.5 py-0.5 text-[10px] rounded-full border border-dashed border-qa-border text-qa-muted hover:text-white"
            onClick={() => setSaving(true)}
          >
            + шаблон
          </button>
        ) : (
          <span className="flex items-center gap-1">
            <input
              className="w-24 bg-transparent border border-qa-border rounded px-1 text-[10px]"
              value={name}
              placeholder="Имя"
              onChange={(e) => setName(e.target.value)}
              autoFocus
            />
            <button type="button" className="text-[10px] text-terminal-accent" onClick={onSave}>
              OK
            </button>
            <button type="button" className="text-[10px] text-qa-muted" onClick={() => setSaving(false)}>
              ×
            </button>
          </span>
        )}
      </div>
    </div>
  );
}
