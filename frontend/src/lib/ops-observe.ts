import { opsApi } from "@/lib/api";

export type OpsObserveView = {
  status?: string;
  backup?: string;
  infra_payment?: string;
  alerts?: string[];
  shadow_diffs?: string;
  live?: boolean;
  partners?: boolean;
  otel?: { sdk?: string; exporter?: string; spans?: string[] };
  slo?: {
    api?: string;
    api_p95_ms?: string;
    report?: string;
    report_seconds?: string;
    sync_timeout_seconds?: string;
    availability?: string;
    backup?: string;
    infra_payment?: string;
    errors?: string;
  };
};

export type OpsPerfView = {
  status?: string;
  checksum?: string;
  elapsed_ms?: string;
  users_executed?: string;
  database_profile?: string;
  worker_limits?: string;
};

export const OPS_DRILLS = [
  "data-provider",
  "broker",
  "queue-overflow",
  "backup-restore",
  "release-rollback",
  "key-compromise",
] as const;

export function opsLines(): string[] {
  return [
    "Наблюдаемость",
    "Бэкап: нет данных",
    "Оплата инфраструктуры: нет данных",
    "Реальный режим выключен",
  ];
}

export async function fetchOpsObserve(): Promise<OpsObserveView | { error: string }> {
  try {
    return (await opsApi.observe()) as OpsObserveView;
  } catch {
    return { error: "нет данных" };
  }
}

export async function runOpsDrill(
  name: string,
): Promise<Record<string, unknown> | { error: string }> {
  try {
    return await opsApi.drill(name);
  } catch {
    return { error: "нет данных" };
  }
}

export async function fetchOpsPerf(): Promise<OpsPerfView | { error: string }> {
  try {
    return (await opsApi.perf()) as OpsPerfView;
  } catch {
    return { error: "нет данных" };
  }
}

export async function runOpsPerf(): Promise<OpsPerfView | { error: string }> {
  try {
    return (await opsApi.runPerf()) as OpsPerfView;
  } catch {
    return { error: "нет данных" };
  }
}
