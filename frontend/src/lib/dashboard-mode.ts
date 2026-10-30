export type DashboardMode = "operator" | "research";

export const DASHBOARD_MODE_KEY = "qa-dashboard-mode";

export function isDashboardMode(value: unknown): value is DashboardMode {
  return value === "operator" || value === "research";
}

/** Read persisted mode (session only). Clears legacy localStorage persistence. */
export function readDashboardMode(): DashboardMode {
  if (typeof window === "undefined") return "operator";

  // Drop old localStorage value so "research" no longer sticks across browser restarts.
  localStorage.removeItem(DASHBOARD_MODE_KEY);

  try {
    const item = sessionStorage.getItem(DASHBOARD_MODE_KEY);
    if (item) {
      const parsed: unknown = JSON.parse(item);
      if (isDashboardMode(parsed)) return parsed;
    }
  } catch {
    /* ignore corrupt storage */
  }

  return "operator";
}

export function writeDashboardMode(mode: DashboardMode): void {
  if (typeof window === "undefined") return;
  try {
    sessionStorage.setItem(DASHBOARD_MODE_KEY, JSON.stringify(mode));
  } catch {
    /* ignore quota / private mode */
  }
}

/** Operator cockpit is the default after login and on fresh visits. */
export function resetDashboardMode(): void {
  if (typeof window === "undefined") return;
  localStorage.removeItem(DASHBOARD_MODE_KEY);
  writeDashboardMode("operator");
}
