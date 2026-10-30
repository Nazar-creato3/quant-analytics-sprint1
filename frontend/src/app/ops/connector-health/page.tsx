"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { OperatorDetailShell } from "@/components/operator/OperatorDetailShell";
import { opsApi } from "@/lib/api";
import { useAuth } from "@/hooks";

export default function ConnectorHealthPage() {
  const { isAdmin } = useAuth();
  const q = useQuery({
    queryKey: ["connector-health"],
    queryFn: () => opsApi.connectorHealth(),
    refetchInterval: 30_000,
  });

  const items = q.data?.items ?? [];

  return (
    <OperatorDetailShell
      title="Connector Health"
      description="Last success + consecutive failures for market data and macro connectors."
    >
      <div className="mb-3 text-xs flex flex-wrap gap-3">
        {isAdmin && (
          <Link href="/ops/crypto-integrations" className="text-terminal-accent hover:text-terminal-accent">
            Integrations Hub →
          </Link>
        )}
        <Link href="/terminal" className="text-terminal-accent hover:text-terminal-accent">
          Terminal →
        </Link>
      </div>
      <div className="cockpit-panel overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="text-left text-qa-muted border-b border-cockpit-border">
              <th className="p-2">Connector</th>
              <th className="p-2">Status</th>
              <th className="p-2">Last success</th>
              <th className="p-2">Failures</th>
              <th className="p-2">Detail</th>
            </tr>
          </thead>
          <tbody>
            {items.map((row: {
              connector_id: string;
              status: string;
              last_success_at?: string | null;
              consecutive_failures?: number;
              detail?: string;
            }) => (
              <tr key={row.connector_id} className="border-b border-cockpit-border/40">
                <td className="p-2 font-mono">{row.connector_id}</td>
                <td className="p-2">{row.status}</td>
                <td className="p-2 tabular-nums">{row.last_success_at ?? "—"}</td>
                <td className="p-2 tabular-nums">{row.consecutive_failures ?? 0}</td>
                <td className="p-2 text-qa-muted">{row.detail ?? ""}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {q.isLoading && <p className="p-3 text-qa-muted">Загрузка…</p>}
        {q.isError && <p className="p-3 text-terminal-down">Не удалось загрузить данные.</p>}
      </div>
    </OperatorDetailShell>
  );
}
