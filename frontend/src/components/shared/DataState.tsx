"use client";

export function DataState({
  loading,
  error,
  empty,
  children,
  emptyText = "Нет данных",
  errorText = "Не удалось загрузить",
  loadingText = "Загрузка…",
}: {
  loading?: boolean;
  error?: boolean;
  empty?: boolean;
  children: React.ReactNode;
  emptyText?: string;
  errorText?: string;
  loadingText?: string;
}) {
  if (loading) return <p className="text-xs text-qa-muted">{loadingText}</p>;
  if (error) return <p className="text-xs text-qa-muted">{errorText}</p>;
  if (empty) return <p className="text-xs text-qa-muted">{emptyText}</p>;
  return <>{children}</>;
}

export function ProvenanceBadge({
  source,
  asOf,
  status = "ready",
}: {
  source: string;
  asOf?: string;
  status?: "ready" | "beta" | "partial";
}) {
  const statusLabel = status === "partial" ? "частично" : status === "beta" ? "проверяется" : "есть данные";
  return (
    <p className="text-[10px] text-qa-muted" data-testid="provenance">
      {statusLabel} · {source}
      {asOf ? ` · ${asOf}` : ""}
    </p>
  );
}
