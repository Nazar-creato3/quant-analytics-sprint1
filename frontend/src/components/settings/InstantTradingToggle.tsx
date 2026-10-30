"use client";

import { useEffect, useState } from "react";
import { getInstantTrading, setInstantTrading } from "@/lib/order-templates";

export function InstantTradingToggle() {
  const [on, setOn] = useState(false);
  useEffect(() => {
    setOn(getInstantTrading());
  }, []);

  return (
    <label className="flex items-start gap-2 rounded-lg border border-qa-border p-3 text-sm">
      <input
        type="checkbox"
        className="mt-1"
        checked={on}
        onChange={(e) => {
          setInstantTrading(e.target.checked);
          setOn(e.target.checked);
        }}
      />
      <span>
        <span className="text-white font-medium">Мгновенная торговля</span>
        <span className="block text-qa-muted text-xs mt-0.5">
          Ордера ниже порога защиты от ошибки ввода отправляются без сводки. Крупные ордера всегда
          требуют подтверждения — этот режим не обходит fat-finger.
        </span>
      </span>
    </label>
  );
}
