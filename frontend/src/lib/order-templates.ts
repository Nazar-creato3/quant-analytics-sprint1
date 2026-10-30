/** Named order-ticket presets. Stored locally — never auto-submit. */

export interface OrderTemplate {
  id: string;
  name: string;
  ticker: string;
  orderType: string;
  sizePct: number;
  slDistancePct: number | null;
  tpDistancePct: number | null;
  tif?: string;
  postOnly?: boolean;
}

const KEY = "qa.orderTemplates.v1";

function readAll(): OrderTemplate[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = window.localStorage.getItem(KEY);
    const parsed = raw ? (JSON.parse(raw) as OrderTemplate[]) : [];
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

function writeAll(items: OrderTemplate[]): void {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(KEY, JSON.stringify(items.slice(0, 24)));
}

export function listOrderTemplates(): OrderTemplate[] {
  return readAll();
}

export function saveOrderTemplate(tpl: Omit<OrderTemplate, "id"> & { id?: string }): OrderTemplate[] {
  const items = readAll();
  const id = tpl.id ?? `tpl-${Date.now()}`;
  const next: OrderTemplate = { ...tpl, id, name: tpl.name.trim() || "Шаблон" };
  const idx = items.findIndex((t) => t.id === id);
  if (idx >= 0) items[idx] = next;
  else items.unshift(next);
  writeAll(items);
  return items;
}

export function deleteOrderTemplate(id: string): OrderTemplate[] {
  const items = readAll().filter((t) => t.id !== id);
  writeAll(items);
  return items;
}

export const INSTANT_TRADING_KEY = "qa.instantTrading.v1";

export function getInstantTrading(): boolean {
  if (typeof window === "undefined") return false;
  return window.localStorage.getItem(INSTANT_TRADING_KEY) === "1";
}

export function setInstantTrading(on: boolean): void {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(INSTANT_TRADING_KEY, on ? "1" : "0");
}
