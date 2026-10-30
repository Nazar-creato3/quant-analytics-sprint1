import type { QueryClient } from "@tanstack/react-query";
import type { Maneuver, PaginatedResponse } from "@/types";
import { maneuversApi } from "@/lib/api";

/** Statuses where a maneuver no longer belongs in the pending-approval panel. */
const RESOLVED_MANEUVER_STATUSES = new Set([
  "approved",
  "executing",
  "filled",
  "rejected",
  "cancelled",
  "invalidated",
]);

export function isResolvedManeuverStatus(status: string | undefined | null): boolean {
  if (!status) return false;
  return RESOLVED_MANEUVER_STATUSES.has(status.toLowerCase());
}

export function isManeuverApproveSuccess(maneuver: Maneuver): boolean {
  const s = maneuver.status.toLowerCase();
  return s === "approved" || s === "executing" || s === "filled";
}

export const PENDING_APPROVAL_QUERY_KEYS = [
  "pending-approvals",
  "decision-feed-pending-maneuvers",
  "decision-feed-maneuvers",
  "decision-feed-latest-report",
  "decision-feed-reports",
] as const;

export function invalidatePendingApprovalQueries(queryClient: QueryClient): void {
  for (const key of PENDING_APPROVAL_QUERY_KEYS) {
    queryClient.invalidateQueries({ queryKey: [key] });
  }
  queryClient.invalidateQueries({ queryKey: ["bottom-orders"] });
  queryClient.invalidateQueries({ queryKey: ["bottom-positions"] });
  queryClient.invalidateQueries({ queryKey: ["bottom-fills"] });
  queryClient.invalidateQueries({ queryKey: ["bottom-manual-orders"] });
  queryClient.invalidateQueries({ queryKey: ["portfolio-metrics"] });
  queryClient.invalidateQueries({ queryKey: ["maneuvers-open-positions"] });
}

type PendingCache = PaginatedResponse<Maneuver> | undefined;

export function optimisticallyRemovePendingManeuver(
  queryClient: QueryClient,
  maneuverId: string,
): PendingCache {
  const prev = queryClient.getQueryData<PaginatedResponse<Maneuver>>(["pending-approvals"]);
  if (prev?.items) {
    queryClient.setQueryData<PaginatedResponse<Maneuver>>(["pending-approvals"], {
      ...prev,
      items: prev.items.filter((m) => m.id !== maneuverId),
      total: Math.max(0, (prev.total ?? prev.items.length) - 1),
    });
  }

  const feedPrev = queryClient.getQueryData<PaginatedResponse<Maneuver>>([
    "decision-feed-pending-maneuvers",
  ]);
  if (feedPrev?.items) {
    queryClient.setQueryData<PaginatedResponse<Maneuver>>(["decision-feed-pending-maneuvers"], {
      ...feedPrev,
      items: feedPrev.items.filter((m) => m.id !== maneuverId),
      total: Math.max(0, (feedPrev.total ?? feedPrev.items.length) - 1),
    });
  }

  return prev;
}

/** If the server already transitioned the maneuver, treat as success instead of error. */
export async function recoverManeuverActionError(
  maneuverId: string,
  action: "approve" | "reject",
): Promise<Maneuver | null> {
  try {
    const maneuver = await maneuversApi.get(maneuverId);
    if (action === "approve" && isManeuverApproveSuccess(maneuver)) return maneuver;
    if (action === "reject" && isResolvedManeuverStatus(maneuver.status)) return maneuver;
    return null;
  } catch {
    return null;
  }
}
