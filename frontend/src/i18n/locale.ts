export const APP_LOCALES = ["ru", "en", "de", "fr"] as const;
export type AppLocale = (typeof APP_LOCALES)[number];

export const DEFAULT_LOCALE: AppLocale = "ru";
export const LOCALE_STORAGE_KEY = "qa.locale";

export const LOCALE_NATIVE_NAMES: Record<AppLocale, string> = {
  ru: "Русский",
  en: "English",
  de: "Deutsch",
  fr: "Français",
};

export function isAppLocale(value: string | null | undefined): value is AppLocale {
  return value === "ru" || value === "en" || value === "de" || value === "fr";
}

export function readStoredLocale(): AppLocale {
  if (typeof window === "undefined") return DEFAULT_LOCALE;
  try {
    const raw = window.localStorage.getItem(LOCALE_STORAGE_KEY);
    if (isAppLocale(raw)) return raw;
  } catch {
    /* ignore */
  }
  return DEFAULT_LOCALE;
}

export function writeStoredLocale(locale: AppLocale): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(LOCALE_STORAGE_KEY, locale);
  } catch {
    /* ignore */
  }
  document.documentElement.lang = locale;
}
