"use client";

import { clsx } from "clsx";

export interface MessengerBubbleProps {
  senderRole: string;
  body: string;
  /** Smaller typography for embedded watchlist chat */
  compact?: boolean;
}

function isAdvisorMessage(role: string): boolean {
  return role === "advisor_ai";
}

export function MessengerBubble({ senderRole, body, compact }: MessengerBubbleProps) {
  const isAdvisor = isAdvisorMessage(senderRole);
  const text = body.replace(/\*\*/g, "");

  return (
    <div
      className={clsx(
        "flex w-full",
        isAdvisor ? "justify-start" : "justify-end",
      )}
    >
      <div
        className={clsx(
          "max-w-[min(100%,34rem)] whitespace-pre-wrap leading-relaxed",
          compact ? "text-[10px] px-2.5 py-1.5 rounded-2xl" : "text-sm px-3 py-2 rounded-2xl",
          isAdvisor
            ? "bg-qa-panel-secondary text-terminal-text rounded-bl-md border border-terminal-border"
            : "bg-[var(--qa-active)] text-terminal-accent rounded-br-md border border-terminal-accent/40",
        )}
      >
        {text}
      </div>
    </div>
  );
}
