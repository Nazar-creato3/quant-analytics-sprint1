"use client";

import { OperatorDetailShell } from "@/components/operator/OperatorDetailShell";
import { NewsPanel } from "@/components/operator/NewsPanel";
import { NEWS_DISPLAY_COUNT } from "@/constants/news";

export default function OperatorNewsPage() {
  return (
    <OperatorDetailShell
      title="Экономические новости"
      description="Макро- и рыночные заголовки из news ingestion pipeline. При отсутствии данных показывается пустое состояние."
    >
      <div className="h-[min(75vh,640px)]">
        <NewsPanel compact={false} maxItems={NEWS_DISPLAY_COUNT} enabled className="w-full h-full max-h-none" />
      </div>
    </OperatorDetailShell>
  );
}
