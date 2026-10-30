export type RiskGateDecision = {
  verdict: "ok" | "warn" | "block";
  reasons: Array<{ code: string; detail: string; number: number | null }>;
  safer: string;
  requires_confirm: boolean;
};

export function explainGate(decision: RiskGateDecision): string {
  if (decision.verdict === "ok") return "Проверка риска пройдена.";
  const why = decision.reasons.map((r) => r.detail).join("; ");
  return `${why}. ${decision.safer}`.trim();
}
