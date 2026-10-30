"use client";

import { clsx } from "clsx";
import type { OrderBookSnapshot } from "@/types";

type SessionStatus = NonNullable<OrderBookSnapshot["session_status"]>;

function statusView(status: SessionStatus | string | null | undefined): {
  label: string;
  color: string;
  dot: string;
  underline?: boolean;
} {
  const v = (status || "").toLowerCase();
  if (v === "open") return { label: "ИДУТ ТОРГИ", color: "text-terminal-up", dot: "bg-[var(--terminal-up)]" };
  if (v === "pre") return { label: "ДО ОТКРЫТИЯ", color: "text-terminal-accent", dot: "bg-terminal-accent" };
  if (v === "post") return { label: "ПОСЛЕ ЗАКРЫТИЯ", color: "text-terminal-accent", dot: "bg-terminal-accent" };
  return { label: "ЗАКРЫТА", color: "text-terminal-down", dot: "bg-[var(--terminal-down)]", underline: true };
}

/** Prominent exchange session banner for order book panels (Terminal Session Clock styling). */
export function OrderBookSessionBanner({ book }: { book: OrderBookSnapshot }) {
  const status = book.session_status;
  const exchange = book.exchange_id;
  if (!exchange || !status) return null;

  const isCryptoOpen = exchange === "BINANCE" && status === "open";
  if (isCryptoOpen) return null;

  const s = statusView(status);
  const isClosedLike = status === "closed" || status === "pre" || status === "post";

  return (
    <div
      className={clsx(
        "mb-2 px-2 py-1.5 rounded border text-center",
        isClosedLike
          ? "border-terminal-down/40 bg-terminal-down/10"
          : "border-terminal-up/30 bg-terminal-up/5",
      )}
    >
      <span className={clsx("inline-flex items-center gap-1.5 text-[10px] font-bold uppercase", s.color)}>
        <span className={clsx("w-1.5 h-1.5 rounded-full shrink-0", s.dot)} aria-hidden />
        <span>{exchange}</span>
        <span
          className={clsx(
            s.underline && "underline decoration-[var(--terminal-down)] underline-offset-2",
          )}
        >
          {s.label}
        </span>
      </span>
      {book.session_message_ru && (
        <p className="text-[10px] text-qa-muted mt-0.5">{book.session_message_ru}</p>
      )}
    </div>
  );
}
