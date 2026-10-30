"use client";

import { OperatorDetailShell } from "@/components/operator/OperatorDetailShell";
import { BottomStrip } from "@/components/operator/BottomStrip";

export default function OperatorPositionsPage() {
  return (
    <OperatorDetailShell
      title="Позиции / Ордера / Закрытые"
      description="Полная ширина страницы. Тяните верхний край шторки, чтобы изменить высоту; таблица прокручивается вниз."
      fillViewport
    >
      <div className="flex-1 min-h-0 w-full max-w-none flex flex-col">
        <BottomStrip enabled resizable fullWidth defaultHeight={420} />
      </div>
    </OperatorDetailShell>
  );
}
