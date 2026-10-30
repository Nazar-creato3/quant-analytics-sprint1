/** Labels for maneuver result control (prompt 40). */

const MISSING = "нет данных";

const KIND_LABELS: Record<string, string> = {
  rebalance: "ребаланс",
  reduce_weight: "снижение доли",
  risk_limit: "лимит риска",
  hedge: "хедж",
  tax_loss: "фиксация убытка",
  replace: "замена",
  regime: "режим",
  deposit: "пополнение",
};

export type ControlRow = {
  maneuver_id?: string;
  kind?: string;
  status?: string;
  actual_return?: string | null;
  expected_return?: string | null;
  do_nothing_return?: string | null;
  counterfactual_return?: string | null;
  quality?: { status?: string };
};

export function kindLabel(kind: string | undefined): string {
  if (!kind) return MISSING;
  return KIND_LABELS[kind] || MISSING;
}

export function numberOrMissing(value: string | null | undefined): string {
  if (value === null || value === undefined || value === "") return MISSING;
  return value;
}

export function controlLines(row: ControlRow): string[] {
  return [
    kindLabel(row.kind),
    `ожидалось ${numberOrMissing(row.expected_return)}`,
    `факт ${numberOrMissing(row.actual_return)}`,
    `бездействие ${numberOrMissing(row.do_nothing_return)}`,
    `если бы исполнили ${numberOrMissing(row.counterfactual_return)}`,
  ];
}
