// Shared helper to turn an axios/unknown error into a human-readable message.
// Prefers the backend-provided `detail` (e.g. risk-gate rejection reason) so the
// operator sees WHY an action failed instead of a generic fallback.

const _TECHNICAL_ERROR_PATTERNS: RegExp[] = [
  /forecast unavailable/i,
  /insufficient market data/i,
  /instrument resolution failed/i,
  /internal server error/i,
  /network error/i,
  /timeout/i,
  /503/i,
  /502/i,
];

function sanitizeUserMessage(message: string, fallback: string): string {
  const trimmed = message.trim();
  if (!trimmed) return fallback;
  if (_TECHNICAL_ERROR_PATTERNS.some((pattern) => pattern.test(trimmed))) {
    return fallback;
  }
  // Hide raw English stack-like fragments for forecast UX.
  if (/^[A-Z][a-z]+ [a-z]+:/.test(trimmed) && /unavailable|insufficient|failed/i.test(trimmed)) {
    return fallback;
  }
  return trimmed;
}

export function isLlmUnavailableMessage(message: string): boolean {
  const m = message.toLowerCase();
  return (
    m.includes("ai tunnel") ||
    m.includes("aitunnel") ||
    (m.includes("пояснение ии") && m.includes("недоступ")) ||
    m.includes("key_limit") ||
    m.includes("лимит ключа") ||
    (m.includes("ai-анализ") && m.includes("недоступ"))
  );
}

export function llmUnavailableUserMessage(_reason?: string | null): string {
  return "Анализ временно недоступен.";
}

export function extractErrorMessage(err: unknown, fallback: string): string {
  if (err && typeof err === "object") {
    const anyErr = err as {
      code?: string;
      response?: { status?: number; data?: { detail?: unknown } };
      message?: string;
    };
    const status = anyErr.response?.status;
    const detail = anyErr.response?.data?.detail;

    if (
      anyErr.code === "ECONNABORTED" ||
      (typeof anyErr.message === "string" && /timeout/i.test(anyErr.message))
    ) {
      return fallback;
    }

    // FastAPI returns `detail` as a string for HTTPException, or a list of
    // validation errors ({msg, loc, ...}) for 422 request-shape failures.
    if (typeof detail === "string" && detail.trim()) {
      return sanitizeUserMessage(detail, fallback);
    }
    if (Array.isArray(detail) && detail.length) {
      const msgs = detail
        .map((d) =>
          d && typeof d === "object" && "msg" in d
            ? String((d as { msg: unknown }).msg)
            : null,
        )
        .filter(Boolean);
      if (msgs.length) return sanitizeUserMessage(msgs.join("; "), fallback);
    }

    if (status === 404) return "Сервис прогноза временно недоступен (404). Повторите позже.";
    if (status === 503) return fallback;
    if (anyErr.message) return sanitizeUserMessage(anyErr.message, fallback);
  }
  return fallback;
}
