"use client";

import { useMutation, useQuery } from "@tanstack/react-query";
import { adminFleetApi } from "@/lib/api";
import { extractErrorMessage } from "@/lib/errors";
import { toast } from "react-hot-toast";

type AccountRow = {
  email: string;
  role?: string;
  account_mode: string;
  venues_connected: string[];
  open_maneuvers: number;
  open_notional_usd: number;
  occupied_tickers: string[];
  grid_tickers: string[];
  closed_90d: number;
  closed_pnl_90d: number;
  last_audit_win_rate?: number | null;
  two_factor?: boolean;
};

function pct(v: number | null | undefined): string {
  if (v == null || Number.isNaN(v)) return "—";
  return `${(v * 100).toFixed(0)}%`;
}

export function FleetAuditPanel({ className }: { className?: string }) {
  const q = useQuery({
    queryKey: ["admin-fleet-audit"],
    queryFn: () => adminFleetApi.snapshot({ limit: 200 }),
    retry: false,
  });

  const refresh = useMutation({
    mutationFn: () => adminFleetApi.refresh(),
    onSuccess: () => {
      toast.success("Сводка счетов обновлена");
      q.refetch();
    },
    onError: (e) => toast.error(extractErrorMessage(e, "Не удалось обновить")),
  });

  const data = q.data as
    | {
        as_of?: string;
        note_ru?: string;
        user_count?: number;
        open_maneuver_count?: number;
        open_notional_usd?: number;
        live_key_users?: number;
        orphan_maneuvers?: number;
        concentration?: { ticker: string; user_count: number; notional_usd: number }[];
        overlaps?: { user_a: string; user_b: string; shared_count: number; shared_tickers: string[] }[];
        calibration_90d?: {
          trade_count: number;
          win_rate: number | null;
          avg_pnl_usd: number | null;
          by_ticker: { ticker: string; n: number; win_rate: number; pnl_usd: number }[];
          by_strategy: { strategy: string; n: number; win_rate: number; pnl_usd: number }[];
        };
        accounts?: AccountRow[];
      }
    | undefined;

  return (
    <div id="accounts" className={className ?? "space-y-4"}>
      {q.isError && (
        <p className="text-sm text-terminal-down">
          {extractErrorMessage(q.error, "Нет доступа. Нужна роль admin.")}
        </p>
      )}
      <div className="flex flex-wrap items-center gap-2">
        <button
          type="button"
          className="btn-primary text-xs"
          disabled={refresh.isPending}
          onClick={() => refresh.mutate()}
        >
          Обновить сейчас
        </button>
        {data?.as_of && (
          <span className="text-[11px] text-qa-muted font-mono">as of {data.as_of}</span>
        )}
      </div>
      {data?.note_ru && <p className="text-xs text-qa-muted">{data.note_ru}</p>}

      {data && (
        <div className="grid grid-cols-2 md:grid-cols-5 gap-2">
          {[
            ["Пользователи", data.user_count],
            ["Открытых идей", data.open_maneuver_count],
            ["Ноционал $", data.open_notional_usd],
            ["Live-ключи", data.live_key_users],
            ["Сироты пайплайна", data.orphan_maneuvers],
          ].map(([label, val]) => (
            <div key={String(label)} className="cockpit-panel p-3">
              <div className="text-[10px] text-qa-muted uppercase">{label}</div>
              <div className="text-sm text-white font-mono">{val ?? "—"}</div>
            </div>
          ))}
        </div>
      )}

      {data?.concentration && data.concentration.length > 0 && (
        <section className="cockpit-panel p-3 overflow-x-auto">
          <h2 className="text-xs font-semibold text-white mb-2">Концентрация тикеров</h2>
          <table className="w-full text-[11px]">
            <thead className="text-qa-muted">
              <tr>
                <th className="text-left py-1">Тикер</th>
                <th className="text-right">Счетов</th>
                <th className="text-right">$</th>
              </tr>
            </thead>
            <tbody>
              {data.concentration.slice(0, 15).map((row) => (
                <tr key={row.ticker} className="border-t border-cockpit-border">
                  <td className="py-1 font-mono">{row.ticker}</td>
                  <td className="text-right">{row.user_count}</td>
                  <td className="text-right font-mono">{row.notional_usd}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}

      {data?.overlaps && data.overlaps.length > 0 && (
        <section className="cockpit-panel p-3 overflow-x-auto">
          <h2 className="text-xs font-semibold text-white mb-2">Пересечения книг</h2>
          <ul className="space-y-1 text-[11px]">
            {data.overlaps.slice(0, 10).map((row) => (
              <li key={`${row.user_a}-${row.user_b}`}>
                <span className="text-white">{row.user_a}</span>
                <span className="text-qa-muted"> × </span>
                <span className="text-white">{row.user_b}</span>
                <span className="text-qa-muted"> — {row.shared_count}: </span>
                <span className="font-mono">{row.shared_tickers.join(", ")}</span>
              </li>
            ))}
          </ul>
        </section>
      )}

      {data?.calibration_90d && (
        <section className="cockpit-panel p-3 overflow-x-auto">
          <h2 className="text-xs font-semibold text-white mb-2">Калибровка закрытых (90д)</h2>
          <p className="text-[11px] text-qa-muted mb-2">
            Сделок: {data.calibration_90d.trade_count} · win{" "}
            {pct(data.calibration_90d.win_rate)} · средний PnL{" "}
            {data.calibration_90d.avg_pnl_usd ?? "—"}
          </p>
          <div className="grid md:grid-cols-2 gap-3">
            <div>
              <div className="text-[10px] text-qa-muted mb-1">Худшие тикеры по сумме</div>
              {(data.calibration_90d.by_ticker || []).slice(0, 8).map((row) => (
                <div key={row.ticker} className="flex justify-between text-[11px] font-mono">
                  <span>{row.ticker}</span>
                  <span>
                    {row.pnl_usd} ({pct(row.win_rate)})
                  </span>
                </div>
              ))}
            </div>
            <div>
              <div className="text-[10px] text-qa-muted mb-1">Стратегии</div>
              {(data.calibration_90d.by_strategy || []).slice(0, 8).map((row) => (
                <div key={row.strategy} className="flex justify-between text-[11px] font-mono">
                  <span>{row.strategy}</span>
                  <span>{row.pnl_usd}</span>
                </div>
              ))}
            </div>
          </div>
        </section>
      )}

      {data?.accounts && (
        <section className="cockpit-panel p-3 overflow-x-auto">
          <h2 className="text-xs font-semibold text-white mb-2">Счета</h2>
          <table className="w-full text-[11px]">
            <thead className="text-qa-muted">
              <tr>
                <th className="text-left py-1">Email</th>
                <th>Режим</th>
                <th className="text-right">Идеи</th>
                <th className="text-right">$</th>
                <th>Занято</th>
                <th>2FA</th>
                <th>Разбор результатов</th>
              </tr>
            </thead>
            <tbody>
              {data.accounts.map((row) => (
                <tr key={row.email} className="border-t border-cockpit-border align-top">
                  <td className="py-1 text-white">{row.email}</td>
                  <td className="font-mono">{row.account_mode}</td>
                  <td className="text-right">{row.open_maneuvers}</td>
                  <td className="text-right font-mono">{row.open_notional_usd}</td>
                  <td className="font-mono max-w-[220px] truncate">
                    {(row.occupied_tickers || []).join(", ") || "—"}
                  </td>
                  <td>{row.two_factor ? "да" : "нет"}</td>
                  <td>{pct(row.last_audit_win_rate)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}
    </div>
  );
}
