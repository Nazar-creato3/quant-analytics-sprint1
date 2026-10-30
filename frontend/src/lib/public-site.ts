export { accuracyPageLines } from "./public-accuracy";

export const SITE_ORIGIN = "https://quantanalyticsclub.ru";

export const AWAITING_COPY = "ожидает текста";

export function siteSections(): { title: string; body: string }[] {
  return [
    { title: "Проблема", body: `Текст основателя: нет данных. Статус: ${AWAITING_COPY}.` },
    { title: "Решение", body: `Текст основателя: нет данных. Статус: ${AWAITING_COPY}.` },
    {
      title: "Как это работает",
      body: `Ограничения расчёта — на странице методики. Маркетинговый текст: нет данных. Статус: ${AWAITING_COPY}.`,
    },
    {
      title: "Безопасность",
      body: "Платёж на этой странице не принимается. Средства не хранятся на площадке. Использование токенов и данных: нет данных.",
    },
  ];
}

export function methodologySections(): { title: string; body: string }[] {
  return [
    { title: "Риск", body: `Публичная формулировка: нет данных. Статус: ${AWAITING_COPY}.` },
    { title: "Доходность", body: `Публичная формулировка: нет данных. Статус: ${AWAITING_COPY}.` },
    { title: "Стресс-сценарии", body: `Публичная формулировка: нет данных. Статус: ${AWAITING_COPY}.` },
    { title: "Концентрация", body: `Публичная формулировка: нет данных. Статус: ${AWAITING_COPY}.` },
    { title: "Манёвры", body: `Публичная формулировка: нет данных. Статус: ${AWAITING_COPY}.` },
  ];
}

export function accuracyLines(): string[] {
  return [
    "Точность прогнозов",
    "Опубликованная точность: нет данных.",
    "Числа журнала на этой странице не выводятся (промпт 49).",
  ];
}

export function teamLines(): string[] {
  return ["Команда", `Состав: нет данных. Статус: ${AWAITING_COPY}.`];
}

export function contactLines(): string[] {
  return ["Контакты", `Адрес и почта: нет данных. Статус: ${AWAITING_COPY}.`];
}

export function legalSlot(title: string): string[] {
  return [title, "Текст не опубликован.", `Статус: ${AWAITING_COPY}.`];
}

export const PUBLIC_SITEMAP_PATHS = [
  "/site",
  "/site/accuracy",
  "/site/team",
  "/site/contacts",
  "/methodology",
  "/pricing",
  "/legal/terms",
  "/legal/privacy",
  "/legal/consent",
  "/legal/disclaimer",
  "/legal/cookies",
] as const;
