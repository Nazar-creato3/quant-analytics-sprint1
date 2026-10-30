/** Labels and filters for the maneuver approval card (prompt 39). */

export const MANEUVER_STATUS_LABELS: Record<string, string> = {
  proposed: "предложен",
  viewed: "просмотрен",
  edited: "отредактирован",
  approved: "одобрен",
  rejected: "отклонён",
  expired: "истёк",
  sent: "отправлен",
  executed_partial: "исполнен частично",
  executed_full: "исполнен полностью",
  executed_paper: "исполнен на бумаге",
  closed: "закрыт",
};

export const REJECT_REASON_OPTIONS = [
  { value: "not_needed", label: "не требуется" },
  { value: "size", label: "размер" },
  { value: "timing", label: "срок" },
  { value: "other", label: "другое" },
] as const;

const MISSING = "нет данных";

export type ManeuverCard = {
  id?: string;
  kind?: string;
  status?: string;
  rationale?: string;
  qty?: string;
  expires_at?: string;
  version?: number;
  orders?: Array<Record<string, string>>;
  impact?: { delta?: Record<string, { before?: unknown; after?: unknown }>; costs?: { total?: string | null } };
  costs?: { total?: string | null; reason?: string };
  diff_vs_original?: Array<{ field?: string; before?: string; after?: string }>;
  reject_reason_label?: string;
  send_block?: string;
};

export function statusLabel(status: string | undefined): string {
  if (!status) return MISSING;
  return MANEUVER_STATUS_LABELS[status] || MISSING;
}

export function costLabel(item: ManeuverCard): string {
  const total = item.costs?.total ?? item.impact?.costs?.total;
  if (total === null || total === undefined || total === "") return MISSING;
  return String(total);
}

export function deadlineLabel(item: ManeuverCard): string {
  if (!item.expires_at) return MISSING;
  return item.expires_at;
}

export function impactLines(item: ManeuverCard): string[] {
  const delta = item.impact?.delta;
  if (!delta) return [MISSING];
  return Object.entries(delta).map(([name, pair]) => {
    const before = pair?.before ?? MISSING;
    const after = pair?.after ?? MISSING;
    return `${name}: ${before} → ${after}`;
  });
}

export function filterByStatus(rows: ManeuverCard[], status: string): ManeuverCard[] {
  if (!status) return rows;
  return rows.filter((row) => row.status === status);
}
