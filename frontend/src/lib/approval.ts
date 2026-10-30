/** Statuses that show Одобрить / Отклонить controls. */
const PENDING_APPROVAL_STATUSES = new Set([
  "pending",
  "pending_approval",
  "awaiting_approval",
]);

const PENDING_DEAL_INTENT_STATUSES = new Set([
  "pending_approval",
  "draft",
  "held",
]);

export function isPendingApproval(status: string | undefined | null): boolean {
  if (!status) return false;
  return PENDING_APPROVAL_STATUSES.has(status.toLowerCase());
}

export function isPendingDealIntent(
  status: string | undefined | null,
  approvalState?: string | null,
): boolean {
  const normalized = (status ?? approvalState ?? "").toLowerCase();
  if (!normalized) return false;
  return (
    PENDING_DEAL_INTENT_STATUSES.has(normalized) ||
    normalized === "pending"
  );
}
