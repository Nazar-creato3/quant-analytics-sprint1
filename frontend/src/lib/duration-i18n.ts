import type { AppLocale } from "@/i18n/locale";

export type DurationLocale = AppLocale;

const PRESET_CANONICAL: Record<string, { ru: string; en: string; de: string; fr: string; api: string }> = {
  scalp: { ru: "быстро · до 90 минут", en: "scalp", de: "Skalp", fr: "scalp", api: "90 минут" },
  day: { ru: "день · до закрытия сессии", en: "day", de: "Tag", fr: "jour", api: "1 день" },
  swing: { ru: "несколько дней", en: "swing", de: "Swing", fr: "swing", api: "7 дней" },
  long: { ru: "долго · недели", en: "long", de: "lang", fr: "long", api: "8 недель" },
};

export const DURATION_PRESET_KEYS = Object.keys(PRESET_CANONICAL);

export function durationPresetApiValue(presetKey: string): string {
  return PRESET_CANONICAL[presetKey]?.api ?? presetKey;
}

export function formatDurationPreset(presetKey: string, locale: DurationLocale = "ru"): string {
  const row = PRESET_CANONICAL[presetKey];
  if (!row) return presetKey;
  return row[locale];
}

export function formatDurationPresets(locale: DurationLocale = "ru"): { key: string; label: string; api: string }[] {
  return DURATION_PRESET_KEYS.map((key) => ({
    key,
    label: formatDurationPreset(key, locale),
    api: durationPresetApiValue(key),
  }));
}

export function formatDurationHorizonLabel(horizon: string | null | undefined, locale: DurationLocale = "ru"): string {
  if (!horizon?.trim()) return "—";
  const trimmed = horizon.trim();
  for (const row of Object.values(PRESET_CANONICAL)) {
    if (trimmed === row.api || trimmed === row.ru || trimmed === row.en || trimmed === row.de || trimmed === row.fr) {
      return row[locale];
    }
  }
  return trimmed;
}

export function durationHorizonExpiredLabel(locale: DurationLocale = "ru"): string {
  if (locale === "en") return "time is up";
  if (locale === "de") return "Frist abgelaufen";
  if (locale === "fr") return "délai écoulé";
  return "срок вышел";
}
