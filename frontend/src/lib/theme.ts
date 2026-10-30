export type ThemeMode = "dark" | "light";

export const THEME_STORAGE_KEY = "qa-theme";

export function isThemeMode(value: unknown): value is ThemeMode {
  return value === "dark" || value === "light";
}

/** Read persisted theme from localStorage (client only). Defaults to dark. */
export function readThemeMode(): ThemeMode {
  if (typeof window === "undefined") return "dark";
  try {
    const raw = localStorage.getItem(THEME_STORAGE_KEY);
    if (!raw) return "dark";
    const parsed: unknown = JSON.parse(raw);
    return isThemeMode(parsed) ? parsed : "dark";
  } catch {
    return "dark";
  }
}

export function writeThemeMode(mode: ThemeMode): void {
  if (typeof window === "undefined") return;
  try {
    localStorage.setItem(THEME_STORAGE_KEY, JSON.stringify(mode));
  } catch {
    /* ignore quota / private mode */
  }
}

/** Apply theme to document root — call before paint to avoid flash. */
export function applyThemeMode(mode: ThemeMode): void {
  if (typeof document === "undefined") return;
  document.documentElement.setAttribute("data-theme", mode);
}
