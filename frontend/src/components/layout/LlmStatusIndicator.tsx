"use client";

import { useQuery } from "@tanstack/react-query";
import { clsx } from "clsx";
import { Brain } from "lucide-react";
import { opsApi } from "@/lib/api";

/**
 * Single global AITunnel / LLM status chip (navbar).
 * Full detail on hover — no full-width page banners.
 */
export function LlmStatusIndicator() {
  const { data } = useQuery({
    queryKey: ["llm-status"],
    queryFn: opsApi.llmStatus,
    refetchInterval: 60_000,
    staleTime: 30_000,
    retry: 1,
  });

  if (!data || data.available) return null;

  const title = "Текстовые пояснения ИИ временно недоступны. Расчёты, данные и графики работают как обычно.";

  return (
    <div
      className={clsx(
        "flex items-center gap-1 px-1.5 py-0.5 rounded border text-[9px] uppercase tracking-wide",
        "border-terminal-accent/50 text-terminal-accent bg-terminal-accent/10",
        "max-w-[140px] sm:max-w-none",
      )}
      title={title}
      role="status"
      aria-live="polite"
    >
      <Brain size={11} className="shrink-0" aria-hidden />
      <span className="truncate">ИИ ограничен</span>
    </div>
  );
}
