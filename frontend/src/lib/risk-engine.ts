export type RiskAttributionRow = {
  ticker: string;
  weight?: number | null;
  var?: number | null;
  es?: number | null;
  pct_of_vol?: number | null;
  pct_of_cvar?: number | null;
  history_note?: string | null;
};

export type RiskAttribution = {
  components?: RiskAttributionRow[];
  enb?: number | null;
  sigma?: number | null;
  es?: number | null;
  weight_basis?: string;
  data_status?: string;
  reason?: string | null;
  partial?: boolean;
  covariance_estimator?: string;
  methodology?: string;
};

export type UnifiedRiskSnapshot = {
  var_95: number;
  var_99: number;
  es_975: number;
  status: string;
  traffic_light: string;
  explain: string;
  incomplete: boolean;
  load_report_hint?: string;
  rubles_var_95: number | null;
  method: string;
  benchmark_id: string;
  as_of?: string;
  source?: string;
  components?: RiskAttributionRow[];
  attribution?: RiskAttribution;
  stress?: { scenarios?: unknown[]; empty?: boolean };
  concentration?: { hhi?: string | null; effective_bets?: string | null };
  what_if?: boolean;
  persisted?: boolean;
  elapsed_ms?: number;
  holdings?: { ticker: string; qty?: string | number | null; price?: string | number | null }[];
};

export function explainVarRubles(): string {
  return "VaR 95% — оценка редкого дневного убытка. ES 97,5% — средний убыток за этим порогом. Это не совет купить или продать.";
}
