export type CycleId = "learn" | "evaluate" | "risk" | "act" | "control" | "service";

export type CycleItem = {
  id: string;
  href: string;
  cycle: CycleId;
};

/** User cycle from TZ 0 / Prompt 18. Service items stay secondary. */
export const IA_CYCLE: { id: CycleId; label: string; items: CycleItem[] }[] = [
  {
    id: "learn",
    label: "Узнать",
    items: [
      { id: "terminal", href: "/terminal", cycle: "learn" },
      { id: "screener", href: "/screener", cycle: "learn" },
      { id: "markets", href: "/markets", cycle: "learn" },
    ],
  },
  {
    id: "evaluate",
    label: "Оценить",
    items: [
      { id: "forecasting", href: "/forecasting", cycle: "evaluate" },
      { id: "chat", href: "/chat", cycle: "evaluate" },
    ],
  },
  {
    id: "risk",
    label: "Проверить риск",
    items: [
      { id: "portfolio", href: "/portfolio", cycle: "risk" },
    ],
  },
  {
    id: "act",
    label: "Действовать",
    items: [
      { id: "act", href: "/act", cycle: "act" },
      { id: "direct-deals", href: "/direct-deals", cycle: "act" },
      { id: "bots", href: "/bots", cycle: "act" },
      { id: "composer", href: "/strategy-composer", cycle: "act" },
    ],
  },
  {
    id: "control",
    label: "Контролировать",
    items: [
      { id: "dashboard", href: "/", cycle: "control" },
      { id: "account", href: "/account", cycle: "control" },
      { id: "settings-notify", href: "/settings#notifications", cycle: "control" },
    ],
  },
  {
    id: "service",
    label: "Служебное",
    items: [
      { id: "platform", href: "/platform", cycle: "service" },
      { id: "settings", href: "/settings", cycle: "service" },
      { id: "admin-ops", href: "/admin/ops", cycle: "service" },
      { id: "methodology", href: "/methodology", cycle: "service" },
    ],
  },
];

export const IA_CYCLE_HREFS = IA_CYCLE.flatMap((g) => g.items.map((i) => i.href));
