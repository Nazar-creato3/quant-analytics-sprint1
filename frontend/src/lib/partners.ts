export function partnerLines(disclosure?: string): string[] {
  return [
    "Открыть счёт у партнёра",
    "Партнёрский путь выключен до договора.",
    `Раскрытие: ${disclosure && disclosure.trim() ? disclosure : "нет данных"}`,
  ];
}
