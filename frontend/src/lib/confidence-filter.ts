/** Structured empty-state metadata from GET /maneuvers when confidence filter blocks all proposals. */
export interface ConfidenceFilterMeta {
  threshold: number;
  max_available_confidence: number | null;
  tradeable_count: number;
  threshold_too_high: boolean;
  suggested_threshold: number | null;
  message: string | null;
}

export function confidenceFilterMessage(
  meta: Record<string, unknown> | null | undefined,
): string | null {
  const block = meta?.confidence_filter;
  if (!block || typeof block !== "object") return null;
  const message = (block as ConfidenceFilterMeta).message;
  return typeof message === "string" && message.trim() ? message : null;
}
