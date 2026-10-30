"use client";

import { useCallback, useEffect, useRef, useState, type PointerEvent as ReactPointerEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { maneuversApi, opsApi, ordersApi, portfolioApi, positionAuditApi } from "@/lib/api";
import type { LiveSnapshotMeta, ManualOrder, Maneuver, PositionsSnapshot } from "@/types";
import { extractErrorMessage } from "@/lib/errors";
import Link from "next/link";
import { toast } from "react-hot-toast";
import { clsx } from "clsx";
import { Octagon, Loader2, Ban, ShieldAlert } from "lucide-react";
import { ReasonState } from "./ReasonState";
import { ConfirmDialog } from "./ConfirmDialog";
import { PositionDetailModal } from "./PositionDetailModal";
import { LiveDataBadge } from "@/components/shared/LiveDataBadge";
import { useDataFreshness } from "@/hooks/useLiveFreshness";
import { useDocumentVisibility } from "@/hooks/useDocumentVisibility";
import { useLivePositionsWebSocket } from "@/hooks/useWebSocket";
import {
  isManeuverCancellable,
  MANEUVER_CANCEL_QUERY_KEYS,
  OPEN_POSITION_STATUS_FILTER,
  CLOSED_POSITION_STATUS_FILTER,
  PENDING_ORDER_STATUS_FILTER,
} from "@/lib/maneuvers";
import {
  expectedPnlRangeTextClass,
  formatExpectedPnlRange,
  formatExpiryCountdown,
  formatUsdPnl,
} from "@/lib/profit-projection";
import { usePositionExpiryCountdown } from "@/hooks/usePositionExpiryCountdown";
import { useUserQueryScope } from "@/hooks/useUserQueryScope";
import { useLocale } from "@/contexts/LocaleContext";
import {
  bookLabelRu,
  closedPriceLabelRu,
  directionLabelRu,
  exitReasonRu,
  positionTruthRu,
  statusLabelRu,
  strategyLabelRu,
} from "@/lib/human-ru";

type TabId = "positions" | "orders" | "fills";

const TABS: { id: TabId; labelKey: string }[] = [
  { id: "positions", labelKey: "positions.tab" },
  { id: "orders", labelKey: "orders.tab" },
  { id: "fills", labelKey: "fills.tab" },
];

function positionsLiveLog(event: string, detail?: unknown) {
  // eslint-disable-next-line no-console
  console.info(`[live-positions] ${new Date().toISOString()} ${event}`, detail ?? "");
}

function formatProfit(value: number): string {
  return formatUsdPnl(value);
}

/** Live unrealized P&L at current price; fall back to a local mark-to-market. */
function unrealizedProfit(m: Maneuver): number | null {
  if (m.unrealized_pnl != null) return m.unrealized_pnl;
  const entry = m.fill_price ?? m.entry_zone_high ?? null;
  const price = m.current_price ?? null;
  if (entry == null || price == null || entry === 0 || !m.position_size_usd) return null;
  const dir = m.direction === "short" ? -1 : 1;
  return ((price - entry) / entry) * m.position_size_usd * dir;
}

/** Client-side countdown from server time_to_close (stable between polls). */
function PositionExpiryCell({
  maneuver,
  syncedAtMs,
}: {
  maneuver: Maneuver;
  syncedAtMs: number | null;
}) {
  const { locale } = useLocale();
  const secs = usePositionExpiryCountdown(
    maneuver.id,
    typeof maneuver.time_to_close === "number" ? maneuver.time_to_close : null,
    syncedAtMs,
    maneuver.horizon_expired,
  );
  if (secs == null) return <>—</>;
  return <>{formatExpiryCountdown(secs, locale)}</>;
}

function PositionsTable({
  items,
  emptyReason,
  onCancel,
  cancelId,
  onOpenDetail,
  fetchedAt,
  dataStale,
  flashIds,
}: {
  items: Maneuver[];
  emptyReason: string;
  onCancel: (id: string) => void;
  cancelId: string | null;
  onOpenDetail: (m: Maneuver) => void;
  fetchedAt: number | null;
  dataStale?: boolean;
  flashIds?: Set<string>;
}) {
  if (items.length === 0) {
    return (
      <ReasonState
        code="no-data"
        title="Нет открытых позиций"
        detail={emptyReason}
        compact
        className="border-0 bg-transparent"
      />
    );
  }

  return (
    <div className="overflow-x-auto -mx-1 px-1">
    <table className="data-table text-[11px] min-w-[620px]">
      <thead>
        <tr>
          {[
            "Тикер",
            "Книга",
            "Статус",
            "Сторона",
            "Размер",
            "Вход",
            "Цена сейчас",
            "Стоп",
            "Цель",
            "Результат сейчас",
          ].map(h => (
            <th key={h} className="py-1.5 whitespace-nowrap">{h}</th>
          ))}
          <th className="py-1.5 whitespace-nowrap text-[12px] font-bold text-qa-text tracking-tight">
            Ожидаемый результат
          </th>
          <th className="py-1.5 whitespace-nowrap">До конца срока</th>
          <th className="py-1.5 whitespace-nowrap" aria-hidden />
          <th className="py-1.5 whitespace-nowrap" aria-hidden />
        </tr>
      </thead>
      <tbody>
        {items.map(m => {
          const unrealized = unrealizedProfit(m);
          return (
            <tr
              key={m.id}
              className={clsx(
                "cursor-pointer hover:bg-cockpit-panel-raised/40 transition-colors duration-500",
                flashIds?.has(m.id) && "bg-terminal-accent/10",
              )}
              onClick={() => onOpenDetail(m)}
            >
              <td className="font-mono font-bold text-white py-1.5">{m.ticker}</td>
              <td className="py-1.5 text-[10px] text-qa-muted" title={positionTruthRu(m)}>
                {bookLabelRu(m.trading_mode)}
              </td>
              <td className="py-1.5">
                <span className={clsx(
                  "badge text-[9px]",
                  m.status === "approved"
                    ? "text-terminal-accent bg-[var(--qa-active)] border-terminal-accent/40"
                    : m.status === "filled"
                      ? "text-terminal-up bg-qa-success-bg border-terminal-up/40"
                      : "text-qa-muted bg-cockpit-panel-raised border-cockpit-border",
                )}>
                  {statusLabelRu(m.status)}
                </span>
              </td>
              <td className="py-1.5">
                <span className={clsx(
                  "badge text-[9px]",
                  m.direction === "long"
                    ? "text-terminal-up bg-qa-success-bg border-terminal-up/40"
                    : "text-terminal-down bg-qa-danger-bg border-terminal-down/40",
                )}>
                  {directionLabelRu(m.direction)}
                </span>
              </td>
              <td className="tabular-nums text-qa-text py-1.5">
                ${m.position_size_usd.toLocaleString("en", { maximumFractionDigits: 0 })}
              </td>
              <td className="tabular-nums text-qa-muted py-1.5">
                {m.fill_price ? `$${m.fill_price.toFixed(2)}` : `$${m.entry_zone_high?.toFixed(2) ?? "—"}`}
              </td>
              <td className={clsx(
                "tabular-nums text-qa-text py-1.5",
                dataStale && "opacity-60",
              )}>
                {m.current_price != null ? `$${m.current_price.toFixed(2)}` : "—"}
              </td>
              <td className="tabular-nums text-terminal-down py-1.5">
                {m.stop_loss ? `$${m.stop_loss.toFixed(2)}` : "—"}
              </td>
              <td className="tabular-nums text-terminal-up py-1.5">
                {m.take_profit ? `$${m.take_profit.toFixed(2)}` : "—"}
              </td>
              <td className={clsx(
                "tabular-nums font-semibold py-1.5",
                dataStale && "opacity-60",
                unrealized == null ? "text-qa-muted" : unrealized >= 0 ? "text-terminal-up" : "text-terminal-down",
              )}>
                {unrealized == null ? "—" : formatProfit(unrealized)}
              </td>
              <td
                className={clsx(
                  "tabular-nums py-1.5 whitespace-nowrap text-[13px] font-semibold",
                  expectedPnlRangeTextClass(m),
                )}
                title={m.profit_disclosure ?? "Ожидаемый результат до конца срока"}
              >
                {formatExpectedPnlRange(m)}
              </td>
              <td className="tabular-nums text-qa-muted py-1.5 whitespace-nowrap font-mono">
                <PositionExpiryCell maneuver={m} syncedAtMs={fetchedAt} />
              </td>
              <td className="py-1.5 text-right" onClick={e => e.stopPropagation()}>
                <Link
                  href={`/cockpit/${encodeURIComponent(m.ticker)}`}
                  className="inline-flex items-center px-1.5 py-0.5 rounded text-[9px] font-semibold text-terminal-accent border border-terminal-accent/40 hover:bg-[var(--qa-active)] whitespace-nowrap"
                >
                  Карточка
                </Link>
              </td>
              <td className="py-1.5 text-right" onClick={e => e.stopPropagation()}>
                {isManeuverCancellable(m.status) && (
                  <button
                    type="button"
                    onClick={() => onCancel(m.id)}
                    disabled={cancelId === m.id}
                    className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[9px] font-semibold text-qa-text border border-qa-border-strong hover:bg-[var(--qa-hover)] disabled:opacity-50"
                    title="Закрыть эту позицию"
                  >
                    {cancelId === m.id ? (
                      <Loader2 size={9} className="animate-spin" />
                    ) : (
                      <Ban size={9} />
                    )}
                    Отменить
                  </button>
                )}
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
    </div>
  );
}

function OrdersTable({
  maneuverItems,
  manualOrders,
  onCancel,
  cancelId,
}: {
  maneuverItems: Maneuver[];
  manualOrders: ManualOrder[];
  onCancel: (id: string) => void;
  cancelId: string | null;
}) {
  const workingManual = manualOrders.filter(o =>
    ["pending", "submitted", "watching", "partial"].includes(o.status),
  );
  const hasRows = maneuverItems.length > 0 || workingManual.length > 0;

  if (!hasRows) {
    return (
      <ReasonState
        code="no-data"
        title="Нет активных ордеров"
        detail="Идеи, которые ждут решения, и заявки, которые уже ушли на биржу, появятся здесь"
        compact
        className="border-0 bg-transparent"
      />
    );
  }

  return (
    <table className="data-table text-[11px]">
      <thead>
        <tr>
          {["Тикер", "Тип", "Статус", "Уверенность", "Размер", "Как смотрим", ""].map(h => (
            <th key={h} className="py-1.5">{h}</th>
          ))}
        </tr>
      </thead>
      <tbody>
        {maneuverItems.map(m => (
          <tr key={`m-${m.id}`}>
            <td className="font-mono font-bold text-white py-1.5">{m.ticker}</td>
            <td className="py-1.5 text-[9px] text-qa-muted">Идея</td>
            <td className="py-1.5">
              <span className="badge text-[9px] text-terminal-accent bg-[var(--qa-active)] border-terminal-accent/40">
                {statusLabelRu(m.status)}
              </span>
            </td>
            <td className="tabular-nums text-qa-muted py-1.5">
              {(m.confidence * 100).toFixed(0)}%
            </td>
            <td className="tabular-nums text-qa-text py-1.5">
              ${m.position_size_usd.toLocaleString("en", { maximumFractionDigits: 0 })}
            </td>
            <td className="text-qa-muted py-1.5">{strategyLabelRu(m.strategy_type)}</td>
            <td className="py-1.5 text-right">
              {isManeuverCancellable(m.status) && (
                <button
                  type="button"
                  onClick={() => onCancel(m.id)}
                  disabled={cancelId === m.id}
                  className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[9px] font-semibold text-qa-text border border-qa-border-strong hover:bg-[var(--qa-hover)] disabled:opacity-50"
                  title="Отменить эту сделку"
                >
                  {cancelId === m.id ? (
                    <Loader2 size={9} className="animate-spin" />
                  ) : (
                    <Ban size={9} />
                  )}
                  Отменить
                </button>
              )}
            </td>
          </tr>
        ))}
        {workingManual.map(o => (
          <tr key={`o-${o.id}`}>
            <td className="font-mono font-bold text-white py-1.5">{o.ticker}</td>
            <td className="py-1.5 text-[9px] text-qa-muted">Заявка</td>
            <td className="py-1.5">
              <span className="badge text-[9px] text-terminal-accent bg-[var(--qa-active)] border-terminal-accent/40">
                {o.status}
              </span>
            </td>
            <td className="tabular-nums text-qa-muted py-1.5">—</td>
            <td className="tabular-nums text-qa-text py-1.5">
              {o.limit_price != null
                ? `$${(o.limit_price * o.quantity).toLocaleString("en", { maximumFractionDigits: 0 })}`
                : `${o.quantity} sh`}
            </td>
            <td className="text-qa-muted py-1.5">{o.order_type} · {o.side}</td>
            <td className="py-1.5 text-right text-[9px] text-qa-muted">—</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function FillsTable({ items }: { items: Maneuver[] }) {
  if (items.length === 0) {
    return (
      <ReasonState
        code="no-data"
        title="Нет закрытых сделок"
        detail="Закрытые идеи появятся здесь"
        compact
        className="border-0 bg-transparent"
      />
    );
  }

  return (
    <table className="data-table text-[11px]">
      <thead>
        <tr>
          {["Тикер", "Книга", "Как закрылась", "Цена", "Результат", "Время"].map(h => (
            <th key={h} className="py-1.5">{h}</th>
          ))}
        </tr>
      </thead>
      <tbody>
        {items.map(m => (
          <tr key={m.id}>
            <td className="font-mono font-bold text-white py-1.5">{m.ticker}</td>
            <td className="py-1.5 text-[10px] text-qa-muted">{bookLabelRu(m.trading_mode)}</td>
            <td className="py-1.5 text-[10px] text-qa-muted">
              {exitReasonRu(m.exit_reason, m.fill_price, m.exit_price)}
            </td>
            <td className="tabular-nums text-qa-text py-1.5 text-[10px]">
              {closedPriceLabelRu(m)}
            </td>
            <td className={clsx(
              "tabular-nums py-1.5",
              (m.realized_pnl ?? 0) >= 0 ? "text-terminal-up" : "text-terminal-down",
            )}>
              {m.realized_pnl != null
                ? `${m.realized_pnl >= 0 ? "+" : ""}$${m.realized_pnl.toFixed(0)}`
                : "—"}
            </td>
            <td className="text-qa-muted py-1.5 text-[10px]">
              {(m.closed_at
                ? new Date(m.closed_at).toLocaleString("ru-RU", {
                    hour: "2-digit", minute: "2-digit", day: "2-digit", month: "2-digit",
                  })
                : m.filled_at
                  ? new Date(m.filled_at).toLocaleString("ru-RU", {
                      hour: "2-digit", minute: "2-digit", day: "2-digit", month: "2-digit",
                    })
                  : "—")}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export function BottomStrip({
  enabled = true,
  resizable = true,
  defaultHeight = 210,
  fullWidth = false,
}: {
  enabled?: boolean;
  /** Drag top edge to resize height (desk layout). */
  resizable?: boolean;
  defaultHeight?: number;
  /** Stretch to page width (positions detail page). */
  fullWidth?: boolean;
}) {
  const { t } = useLocale();
  const [tab, setTab] = useState<TabId>("positions");
  const [cancelId, setCancelId] = useState<string | null>(null);
  const [confirmCloseAll, setConfirmCloseAll] = useState(false);
  const [confirmFireFight, setConfirmFireFight] = useState(false);
  const [detailManeuver, setDetailManeuver] = useState<Maneuver | null>(null);
  const [liveSnapshot, setLiveSnapshot] = useState<LiveSnapshotMeta | null>(null);
  const [snapshotReceivedAt, setSnapshotReceivedAt] = useState<number | null>(null);
  const [flashIds, setFlashIds] = useState<Set<string>>(new Set());
  const prevSigRef = useRef<Map<string, string>>(new Map());
  const queryClient = useQueryClient();
  const { scopedKey, userKey } = useUserQueryScope();
  const tabVisible = useDocumentVisibility();
  const STRIP_H_KEY = "operator:bottom-strip-h";
  /** 0 = table hidden, tabs stay — chart can use almost the full desk height. */
  const MIN_STRIP_H = 0;
  const clampStripH = useCallback((n: number) => {
    const maxH =
      typeof window !== "undefined" ? Math.max(160, window.innerHeight - 120) : 900;
    return Math.min(maxH, Math.max(MIN_STRIP_H, n));
  }, []);
  const [stripHeight, setStripHeight] = useState(defaultHeight);
  const dragRef = useRef<{ startY: number; startH: number } | null>(null);

  useEffect(() => {
    if (typeof window === "undefined") return;
    const raw = window.localStorage.getItem(STRIP_H_KEY);
    const n = raw ? Number(raw) : NaN;
    if (Number.isFinite(n)) setStripHeight(clampStripH(n));
  }, [clampStripH]);

  const onResizePointerDown = useCallback((e: ReactPointerEvent<HTMLDivElement>) => {
    if (!resizable) return;
    e.preventDefault();
    (e.target as HTMLElement).setPointerCapture?.(e.pointerId);
    dragRef.current = { startY: e.clientY, startH: stripHeight };
  }, [resizable, stripHeight]);

  const onResizePointerMove = useCallback((e: ReactPointerEvent<HTMLDivElement>) => {
    if (!dragRef.current) return;
    const dy = dragRef.current.startY - e.clientY;
    setStripHeight(clampStripH(dragRef.current.startH + dy));
  }, [clampStripH]);

  const onResizeDoubleClick = useCallback(() => {
    if (!resizable) return;
    setStripHeight((h) => {
      const next = h > 24 ? 0 : defaultHeight;
      if (typeof window !== "undefined") {
        window.localStorage.setItem(STRIP_H_KEY, String(next));
      }
      return next;
    });
  }, [resizable, defaultHeight]);

  const onResizePointerUp = useCallback(() => {
    if (!dragRef.current) return;
    dragRef.current = null;
    if (typeof window !== "undefined") {
      window.localStorage.setItem(STRIP_H_KEY, String(stripHeight));
    }
  }, [stripHeight]);

  const cancelMutation = useMutation({
    mutationFn: (id: string) => maneuversApi.cancel(id),
    onMutate: id => setCancelId(id),
    onSettled: () => setCancelId(null),
    onSuccess: (result) => {
      toast.success(result.message || "Сделка отменена");
      for (const key of MANEUVER_CANCEL_QUERY_KEYS) {
        queryClient.invalidateQueries({ queryKey: [key] });
      }
    },
    onError: (err) => toast.error(extractErrorMessage(err, "Не удалось отменить сделку")),
  });

  const closeAllMutation = useMutation({
    mutationFn: () => opsApi.closeAllPositions(),
    onSuccess: (result) => {
      if (result.closed_count === 0 && result.cancelled_count === 0) {
        toast("Нет открытых позиций для закрытия", { icon: "ℹ️" });
      } else {
        toast.success(result.message || "Позиции закрыты", { duration: 7000 });
      }
      queryClient.invalidateQueries({ queryKey: scopedKey("bottom-positions") });
      queryClient.invalidateQueries({ queryKey: scopedKey("bottom-orders") });
      queryClient.invalidateQueries({ queryKey: scopedKey("bottom-fills") });
      queryClient.invalidateQueries({ queryKey: scopedKey("portfolio-metrics") });
      queryClient.invalidateQueries({ queryKey: ["pending-approvals"] });
      queryClient.invalidateQueries({ queryKey: ["decision-feed-maneuvers"] });
      queryClient.invalidateQueries({ queryKey: ["maneuvers-open-positions"] });
    },
    onError: (err) => toast.error(extractErrorMessage(err, "Не удалось закрыть позиции")),
  });

  const {
    data: executing,
    isLoading: loadingPos,
    dataUpdatedAt: positionsUpdatedAt,
    isError: positionsError,
    refetch: refetchPositions,
  } = useQuery({
    queryKey: scopedKey("bottom-positions"),
    queryFn: async () => {
      const result = await maneuversApi.list({ status: OPEN_POSITION_STATUS_FILTER, page_size: 50 });
      positionsLiveLog("poll_ok", { count: result.items.length });
      const snap = result.meta?.live_snapshot as LiveSnapshotMeta | undefined;
      if (snap) {
        setLiveSnapshot(snap);
        setSnapshotReceivedAt(Date.now());
      }
      return result;
    },
    refetchInterval: tabVisible ? 15_000 : false,
    refetchIntervalInBackground: false,
    enabled,
  });

  const onWsSnapshot = useCallback(
    (snapshot: PositionsSnapshot) => {
      positionsLiveLog("ws_snapshot", {
        count: snapshot.total,
        stale: snapshot.live_snapshot?.stale,
      });
      setSnapshotReceivedAt(Date.now());
      setLiveSnapshot(snapshot.live_snapshot);
      queryClient.setQueryData(scopedKey("bottom-positions"), (prev: typeof executing | undefined) => ({
        ...(prev ?? { total: snapshot.total, page: 1, page_size: 50, pages: 1 }),
        items: snapshot.items,
        total: snapshot.total,
        meta: { ...(prev?.meta ?? {}), live_snapshot: snapshot.live_snapshot },
      }));
    },
    [queryClient, scopedKey],
  );

  const { connectionState: positionsWsState } = useLivePositionsWebSocket(
    enabled,
    onWsSnapshot,
    userKey,
  );
  const wsConnected = positionsWsState === "live";

  const positionsFetchedAt = positionsUpdatedAt > 0 ? positionsUpdatedAt : null;
  const serverNowIso = liveSnapshot?.server_now ?? null;
  /** Pair server_now with the local receipt timestamp from the same REST/WS snapshot. */
  const countdownAnchorMs = snapshotReceivedAt ?? positionsFetchedAt;
  const freshnessAnchor =
    wsConnected && snapshotReceivedAt
      ? snapshotReceivedAt
      : positionsFetchedAt;

  const positionsFreshness = useDataFreshness(freshnessAnchor);
  const dataStaleFlag =
    liveSnapshot?.stale === true ||
    positionsFreshness.state !== "live" ||
    (liveSnapshot?.data_freshness_seconds ?? 0) > 45;

  useEffect(() => {
    const items = executing?.items ?? [];
    const nextFlash = new Set<string>();
    for (const m of items) {
      const sig = `${m.current_price ?? ""}|${m.unrealized_pnl ?? ""}|${m.time_to_close ?? ""}`;
      const prev = prevSigRef.current.get(m.id);
      if (prev != null && prev !== sig) nextFlash.add(m.id);
      prevSigRef.current.set(m.id, sig);
    }
    if (nextFlash.size > 0) {
      setFlashIds(nextFlash);
      const t = setTimeout(() => setFlashIds(new Set()), 900);
      return () => clearTimeout(t);
    }
  }, [executing?.items, positionsUpdatedAt]);

  const lastStaleRefetchAtRef = useRef(0);
  const prevPositionsFreshnessRef = useRef(positionsFreshness.state);

  // Refetch when data goes stale — but NOT on every ageLabel tick (1 Hz clock
  // was firing refetch every second and freezing the dashboard).
  useEffect(() => {
    if (!enabled) return;
    const state = positionsFreshness.state;
    const prev = prevPositionsFreshnessRef.current;
    prevPositionsFreshnessRef.current = state;

    if (state !== "stale" && state !== "disconnected") return;

    const now = Date.now();
    const transitioned =
      prev !== state && (state === "stale" || state === "disconnected");
    const throttled = now - lastStaleRefetchAtRef.current >= 30_000;
    if (!transitioned && !throttled) return;

    lastStaleRefetchAtRef.current = now;
    positionsLiveLog("stale_refetch", {
      state,
      transitioned,
      age: positionsFreshness.ageLabel,
    });
    void refetchPositions();
  }, [enabled, positionsFreshness.state, positionsFreshness.ageLabel, refetchPositions]);

  const { data: orders, isLoading: loadingOrders } = useQuery({
    queryKey: scopedKey("bottom-orders"),
    queryFn: () => maneuversApi.list({ status: PENDING_ORDER_STATUS_FILTER, page_size: 50 }),
    refetchInterval: 15_000,
    enabled,
  });

  const { data: manualOrders, isLoading: loadingManualOrders } = useQuery({
    queryKey: scopedKey("bottom-manual-orders"),
    queryFn: () => ordersApi.list(),
    refetchInterval: 15_000,
    enabled,
  });

  const { data: filled, isLoading: loadingFills } = useQuery({
    queryKey: scopedKey("bottom-fills"),
    queryFn: () => maneuversApi.list({ status: CLOSED_POSITION_STATUS_FILTER, page_size: 500 }),
    refetchInterval: 15_000,
    refetchIntervalInBackground: true,
    enabled,
  });

  const { data: portfolioMetrics } = useQuery({
    queryKey: scopedKey("portfolio-metrics"),
    queryFn: portfolioApi.metrics,
    enabled,
    staleTime: 30_000,
  });

  const { data: auditStatus } = useQuery({
    queryKey: scopedKey("position-audit-status"),
    queryFn: positionAuditApi.status,
    enabled,
    refetchInterval: 30_000,
  });

  const triggerAuditMutation = useMutation({
    mutationFn: positionAuditApi.trigger,
    onSuccess: (result) => {
      queryClient.invalidateQueries({ queryKey: scopedKey("position-audit-status") });
      if (result.status === "queued") {
        toast.success("Аудит позиций поставлен в очередь");
      } else if (result.status === "already_running") {
        toast("Аудит уже выполняется");
      } else {
        toast(result.message_ru || `Собрано ${result.expiration_close_count} из ${result.required_count ?? 100}`);
      }
    },
    onError: (err) => toast.error(extractErrorMessage(err, "Аудит не удалось запустить")),
  });

  const fireFightMutation = useMutation({
    mutationFn: async () => {
      const positions = executing?.items ?? [];
      const losing = positions
        .filter(m => (m.unrealized_pnl ?? 0) < 0)
        .sort((a, b) => (a.unrealized_pnl ?? 0) - (b.unrealized_pnl ?? 0));
      let closed = 0;
      for (const m of losing) {
        await maneuversApi.cancel(m.id, { reason: "partial fire-fight — losing position" });
        closed += 1;
      }
      return closed;
    },
    onSuccess: (closed) => {
      setConfirmFireFight(false);
      if (closed === 0) {
        toast("Нет убыточных позиций для закрытия", { icon: "ℹ️" });
      } else {
        toast.success(`Fire-fight: закрыто ${closed} убыточных позиций`, { duration: 7000 });
      }
      for (const key of MANEUVER_CANCEL_QUERY_KEYS) {
        queryClient.invalidateQueries({ queryKey: [key] });
      }
    },
    onError: (err) => toast.error(extractErrorMessage(err, "Fire-fight не удался")),
  });

  const isLoading = loadingPos || loadingOrders || loadingFills || loadingManualOrders;
  const orderManeuvers = (orders?.items ?? []).filter(m => m.strategy_type !== "no_trade");
  const workingManualCount = (manualOrders ?? []).filter(o =>
    ["pending", "submitted", "watching", "partial"].includes(o.status),
  ).length;
  const orderCount = orderManeuvers.length + workingManualCount;
  const openCount = executing?.items.length ?? 0;
  const losingCount = (executing?.items ?? []).filter(m => (m.unrealized_pnl ?? 0) < 0).length;
  const openUnrealizedSum = (executing?.items ?? []).reduce(
    (sum, m) => sum + (m.unrealized_pnl ?? 0),
    0,
  );
  const closedRealizedSum = (filled?.items ?? []).reduce(
    (sum, m) => sum + (m.realized_pnl ?? 0),
    0,
  );

  return (
    <div
      className={clsx(
        "cockpit-bottom-strip shrink-0 flex flex-col",
        fullWidth && "w-full max-w-none",
      )}
    >
      {resizable ? (
        <div
          role="separator"
          aria-orientation="horizontal"
          aria-label="Изменить высоту шторки позиций"
          title="Потяните вниз — почти до низа экрана. Двойной клик — свернуть / развернуть"
          onDoubleClick={onResizeDoubleClick}
          onPointerDown={onResizePointerDown}
          onPointerMove={onResizePointerMove}
          onPointerUp={onResizePointerUp}
          onPointerCancel={onResizePointerUp}
          className="h-2 cursor-ns-resize flex items-center justify-center border-b border-cockpit-border bg-cockpit-panel-raised/40 hover:bg-terminal-accent/20 touch-none select-none"
        >
          <span className="block w-10 h-0.5 rounded-full bg-qa-muted/60" />
        </div>
      ) : null}
      {tab === "positions" && openCount > 0 && stripHeight > 40 && (
        <div className="flex items-center justify-end gap-2 px-3 py-2 border-b border-cockpit-border bg-cockpit-panel/40">
          {losingCount > 0 && (
            <button
              type="button"
              onClick={() => setConfirmFireFight(true)}
              disabled={fireFightMutation.isPending}
              className={clsx(
                "inline-flex items-center gap-1 px-2 py-1 text-[10px] font-semibold uppercase tracking-wide alert-caution-panel",
                "disabled:opacity-50",
              )}
              title="Частичное закрытие — только убыточные позиции"
            >
              {fireFightMutation.isPending ? (
                <Loader2 size={10} className="animate-spin" />
              ) : (
                <ShieldAlert size={10} />
              )}
              Тушение ({losingCount})
            </button>
          )}
          <button
            type="button"
            onClick={() => setConfirmCloseAll(true)}
            disabled={closeAllMutation.isPending}
            className={clsx(
              "inline-flex items-center gap-1 px-2 py-1 text-[10px] font-bold uppercase tracking-wide btn-danger-subtle",
              "disabled:opacity-50",
            )}
            title="Закрыть все открытые позиции"
          >
            {closeAllMutation.isPending ? (
              <Loader2 size={10} className="animate-spin" />
            ) : (
              <Octagon size={10} />
            )}
            Закрыть все
          </button>
        </div>
      )}

      {tab === "fills" && (
        <div className="flex items-center justify-between gap-3 px-3 py-2 border-b border-cockpit-border bg-cockpit-panel/40">
          <div className="min-w-0">
            <div className="text-[10px] font-semibold uppercase tracking-wide text-qa-text">
              Аудит закрытых позиций
            </div>
            <div className="text-[10px] text-qa-muted truncate">
              {auditStatus?.message_ru
                ?? "Аудит закрытых позиций — после каждой закрытой сделки"}
            </div>
          </div>
          <button
            type="button"
            onClick={() => triggerAuditMutation.mutate()}
            disabled={
              triggerAuditMutation.isPending ||
              Boolean(auditStatus?.audit_running) ||
              !auditStatus?.ready_to_trigger
            }
            className={clsx(
              "inline-flex items-center gap-1 px-2 py-1 text-[10px] font-bold uppercase tracking-wide rounded border",
              "border-terminal-accent/50 text-terminal-accent hover:bg-[var(--qa-active)] disabled:opacity-50 disabled:hover:bg-transparent",
            )}
            title={
              auditStatus?.ready_to_trigger
                ? "Запустить аудит новых закрытых сделок"
                : auditStatus?.message_ru ?? "Аудит запустится сам после закрытия сделки"
            }
          >
            {triggerAuditMutation.isPending ? <Loader2 size={10} className="animate-spin" /> : null}
            Начать аудит
          </button>
        </div>
      )}

      <div className="flex items-center justify-between gap-2 px-3 pt-2 border-b border-cockpit-border">
        <div className="flex items-center gap-1">
        {TABS.map((tabDef) => (
          <button
            key={tabDef.id}
            onClick={() => setTab(tabDef.id)}
            className={clsx(
              "px-3 py-1.5 text-[10px] font-semibold uppercase tracking-wide rounded-t transition-colors",
              tab === tabDef.id
                ? "bg-cockpit-panel-raised text-qa-text border border-b-0 border-cockpit-border-strong -mb-px"
                : "text-qa-muted hover:text-qa-text",
            )}
          >
            {t(tabDef.labelKey)}
            <span className="ml-1.5 text-qa-muted tabular-nums">
              {tabDef.id === "positions" ? openCount
                : tabDef.id === "orders" ? orderCount
                : (filled?.items.length ?? 0)}
            </span>
          </button>
        ))}
        </div>
        <LiveDataBadge
          state={positionsError ? "disconnected" : positionsFreshness.state}
          ageLabel={positionsFreshness.ageLabel}
          wsConnected={wsConnected}
          compact
          className="mr-2"
        />
        {portfolioMetrics && (
          <span
            className="hidden lg:inline text-[9px] font-mono text-qa-muted mr-2 tabular-nums"
            title={`Σ открытые uP&L ${formatProfit(openUnrealizedSum)} · Σ закрытые rP&L ${formatProfit(closedRealizedSum)} · header uP&L ${formatProfit(portfolioMetrics.unrealized_pnl_usd ?? 0)} · rP&L ${formatProfit(portfolioMetrics.realized_pnl_usd ?? 0)}`}
          >
            uP&L {formatProfit(portfolioMetrics.unrealized_pnl_usd ?? openUnrealizedSum)}
          </span>
        )}
        <Link
          href="/operator/positions"
          className="text-[10px] text-qa-muted hover:text-qa-text uppercase tracking-wide"
        >
          На всю ширину →
        </Link>
      </div>

      <div
        className={clsx(
          "overflow-y-auto overflow-x-auto",
          stripHeight > 0 ? "px-3 py-2" : "px-0 py-0",
        )}
        style={{ height: stripHeight, minHeight: 0 }}
      >
        {isLoading ? (
          <ReasonState code="loading" title="Загрузка…" compact className="border-0 bg-transparent py-4" />
        ) : tab === "positions" ? (
          <PositionsTable
            items={executing?.items ?? []}
            emptyReason="Нет открытых позиций — одобрите идею, она появится здесь"
            onCancel={id => cancelMutation.mutate(id)}
            cancelId={cancelId}
            onOpenDetail={setDetailManeuver}
            fetchedAt={countdownAnchorMs}
            dataStale={dataStaleFlag}
            flashIds={flashIds}
          />
        ) : tab === "orders" ? (
          <OrdersTable
            maneuverItems={orderManeuvers}
            manualOrders={manualOrders ?? []}
            onCancel={id => cancelMutation.mutate(id)}
            cancelId={cancelId}
          />
        ) : (
          <FillsTable items={filled?.items ?? []} />
        )}
      </div>

      <ConfirmDialog
        open={confirmCloseAll}
        title="Закрыть все позиции?"
        message="Закрыть все открытые позиции? Результат посчитаем по последней цене."
        confirmLabel="Да, закрыть все"
        loading={closeAllMutation.isPending}
        onCancel={() => setConfirmCloseAll(false)}
        onConfirm={() => {
          closeAllMutation.mutate(undefined, {
            onSuccess: () => setConfirmCloseAll(false),
          });
        }}
      />

      <ConfirmDialog
        open={confirmFireFight}
        variant="caution"
        title="Закрыть убыточные?"
        message={`Закрыть ${losingCount} убыточных позиций? Прибыльные позиции останутся открытыми.`}
        confirmLabel="Закрыть убыточные"
        loading={fireFightMutation.isPending}
        onCancel={() => setConfirmFireFight(false)}
        onConfirm={() => fireFightMutation.mutate()}
      />

      {detailManeuver && (
        <PositionDetailModal maneuver={detailManeuver} onClose={() => setDetailManeuver(null)} />
      )}
    </div>
  );
}
