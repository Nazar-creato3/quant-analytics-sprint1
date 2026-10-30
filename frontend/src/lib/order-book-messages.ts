import type { OrderBookSnapshot } from "@/types";

/** User-facing copy when the exchange session is closed (non-admin). */
export const USER_SESSION_CLOSED_MESSAGE =
  "Торговая сессия закрыта. Глубина стакана недоступна вне часов работы биржи";

function isClosedLikeSession(book: OrderBookSnapshot): boolean {
  const st = (book.session_status || "").toLowerCase();
  return st === "closed" || st === "pre" || st === "post";
}

/** Short message shown to all users when depth is unavailable after hours. */
export function orderBookUserFacingMessage(book: OrderBookSnapshot): string | null {
  if (book.depth_available !== false) return null;
  if (book.exchange_id === "BINANCE") return null;
  if (isClosedLikeSession(book)) return USER_SESSION_CLOSED_MESSAGE;
  if (book.session_message_ru && !looksLikeProviderDiagnostic(book.session_message_ru)) {
    return book.session_message_ru;
  }
  const label = book.session_label;
  if (label && !looksLikeProviderDiagnostic(label)) return label;
  if (book.exchange_id && book.exchange_id !== "BINANCE") {
    return "Глубина стакана временно ограничена";
  }
  return null;
}

function looksLikeProviderDiagnostic(text: string): boolean {
  const lower = text.toLowerCase();
  return (
    lower.includes("429") ||
    lower.includes("polygon") ||
    lower.includes("alpaca") ||
    lower.includes("finnhub") ||
    lower.includes("yahoo") ||
    lower.includes("fallback") ||
    lower.includes("http") ||
    lower.includes("credits") ||
    lower.includes("polygon:") ||
    lower.includes("alpaca:")
  );
}

/** Full provider / API diagnostics — admin eyes only. */
export function orderBookAdminDiagnostics(book: OrderBookSnapshot): string | null {
  const reason = book.depth_unavailable_reason?.trim();
  if (!reason) return null;
  const userMsg = USER_SESSION_CLOSED_MESSAGE;
  if (reason === userMsg) return null;
  return reason;
}
