"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { clsx } from "clsx";
import { maneuversApi } from "@/lib/api";
import { OPEN_POSITION_STATUS_FILTER, PENDING_ORDER_STATUS_FILTER } from "@/lib/maneuvers";
import { formatUsdPnl } from "@/lib/profit-projection";
import { ReasonState } from "@/components/operator/ReasonState";
import { Spinner } from "@/components/ui";
import type { Maneuver } from "@/types";
import { useMobilePollingInterval } from "@/hooks/useIsMobile";

function unrealizedProfit(m: Maneuver): number | null {
  if (m.unrealized_pnl != null) return m.unrealized_pnl;
  const entry = m.fill_price ?? m.entry_zone_high ?? null;
  const price = m.current_price ?? null;
  if (entry == null || price == null || entry === 0 || !m.position_size_usd) return null;
  const dir = m.direction === "short" ? -1 : 1;
  return ((price - entry) / entry) * m.position_size_usd * dir;
}

function PositionCard({ m }: { m: Maneuver }) {
  const pnl = unrealizedProfit(m);
  const up = (pnl ?? 0) >= 0;

  return (
    <div className="rounded-xl border border-cockpit-border bg-cockpit-panel-raised p-3">
      <div className="flex items-start justify-between gap-2">
        <div>
          <p className="font-mono font-semibold text-white text-base">{m.ticker}</p>
          <p className="text-[10px] text-qa-muted uppercase mt-0.5">
            {m.direction} · {m.status}
          </p>
        </div>
        <div className="text-right">
          <p className="font-mono tabular-nums text-white text-sm">
            {m.current_price != null ? `$${Number(m.current_price).toFixed(2)}` : "—"}
          </p>
          {pnl != null && (
            <p className={clsx("font-mono tabular-nums text-sm", up ? "text-terminal-up" : "text-terminal-down")}>
              {formatUsdPnl(pnl)}
            </p>
          )}
        </div>
      </div>
      <div className="mt-2 flex flex-wrap gap-x-3 gap-y-1 text-[10px] text-qa-muted">
        {m.position_size_usd != null && (
          <span>
            Размер <span className="font-mono text-qa-text">${Math.round(m.position_size_usd).toLocaleString()}</span>
          </span>
        )}
        {m.fill_price != null && (
          <span>
            Вход <span className="font-mono text-qa-text">${Number(m.fill_price).toFixed(2)}</span>
          </span>
        )}
      </div>
    </div>
  );
}

export function MobilePositionsPreview() {
  const pollInterval = useMobilePollingInterval(15_000, 60_000);

  const { data: positions, isLoading: loadingPos } = useQuery({
    queryKey: ["bottom-positions"],
    queryFn: () => maneuversApi.list({ status: OPEN_POSITION_STATUS_FILTER, page_size: 20 }),
    refetchInterval: pollInterval,
  });

  const { data: orders, isLoading: loadingOrders } = useQuery({
    queryKey: ["bottom-orders"],
    queryFn: () => maneuversApi.list({ status: PENDING_ORDER_STATUS_FILTER, page_size: 10 }),
    refetchInterval: pollInterval,
  });

  const openItems = positions?.items ?? [];
  const pendingOrders = orders?.items ?? [];
  const isLoading = loadingPos || loadingOrders;

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between gap-2">
        <h3 className="text-xs uppercase text-qa-muted font-bold tracking-wide">Позиции и сделки</h3>
        <Link
          href="/operator/positions"
          className="text-[10px] uppercase tracking-wide text-terminal-accent min-h-[44px] flex items-center"
        >
          Все →
        </Link>
      </div>

      {isLoading && openItems.length === 0 && pendingOrders.length === 0 ? (
        <div className="flex justify-center py-4">
          <Spinner size={20} />
        </div>
      ) : openItems.length === 0 && pendingOrders.length === 0 ? (
        <ReasonState
          code="no-data"
          title="Нет открытых позиций"
          detail="Одобрите маневр — позиция появится здесь"
          compact
          className="border-0 bg-transparent"
        />
      ) : (
        <div className="space-y-2">
          {openItems.slice(0, 4).map((m) => (
            <PositionCard key={m.id} m={m} />
          ))}
          {pendingOrders.length > 0 && (
            <div className="pt-1">
              <p className="text-[10px] font-bold uppercase tracking-wider text-terminal-accent mb-2">
                Ожидают исполнения · {pendingOrders.length}
              </p>
              {pendingOrders.slice(0, 2).map((m) => (
                <PositionCard key={m.id} m={m} />
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
