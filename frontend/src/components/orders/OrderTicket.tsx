"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { PretradeImpact } from "@/components/orders/PretradeImpact";
import { classifySymbol } from "@/lib/asset-class";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { clsx } from "clsx";
import { Loader2, AlertTriangle } from "lucide-react";
import { toast } from "react-hot-toast";
import { ordersApi } from "@/lib/api";
import { useAuth } from "@/hooks";
import { explainGate } from "@/lib/risk-gate";
import { extractErrorMessage } from "@/lib/errors";
import { formatDurationHorizonLabel, formatDurationPresets } from "@/lib/duration-i18n";
import { useVisiblePollInterval } from "@/hooks/useDocumentVisibility";
import type { ManualOrder, OrderTicketPrefill } from "@/types";
import { OrderBookDepth } from "./OrderBookDepth";
import { OrderConfirmSummary } from "./OrderConfirmSummary";
import { OrderMarginNote } from "./OrderMarginNote";
import { estimateOrderPreview } from "@/lib/order-preview";

export type OrderSide = "buy" | "sell";
export type OrderType =
  | "market"
  | "limit"
  | "stop"
  | "stop_limit"
  | "oco"
  | "trailing_stop";
export type TimeInForce = "gtc" | "ioc" | "fok" | "day" | "gtd";

const ORDER_TYPES: { value: OrderType; label: string }[] = [
  { value: "market", label: "По рынку" },
  { value: "limit", label: "По своей цене" },
  { value: "stop", label: "Стоп" },
  { value: "stop_limit", label: "Стоп-лимит" },
  { value: "oco", label: "Одна из двух" },
  { value: "trailing_stop", label: "Следящий стоп" },
];

const TIF_OPTIONS: { value: TimeInForce; label: string }[] = [
  { value: "gtc", label: "Пока не отменю" },
  { value: "day", label: "До конца дня" },
  { value: "gtd", label: "До выбранной даты" },
  { value: "ioc", label: "Сразу, остаток отменить" },
  { value: "fok", label: "Сразу целиком или отмена" },
];

const PCT_BUTTONS = [25, 50, 75, 100];
const POSITION_DURATION_PRESETS = formatDurationPresets("ru");
/** Notional above this USD triggers fat-finger confirmation */
const FAT_FINGER_NOTIONAL_USD = 25_000;
/** Or above this fraction of available balance */
const FAT_FINGER_BALANCE_FRACTION = 0.25;

interface OrderTicketProps {
  ticker: string;
  prefill?: OrderTicketPrefill | null;
  availableBalanceUsd?: number;
  onSubmitted?: (order: ManualOrder) => void;
  compact?: boolean;
  /** Sync limit price from external order book click */
  externalLimitPrice?: number;
  onSideChange?: (side: OrderSide) => void;
  showOrderBook?: boolean;
  bookPollMs?: number;
  quoteBid?: number | null;
  quoteAsk?: number | null;
}

export function OrderTicket({
  ticker,
  prefill,
  availableBalanceUsd = 100_000,
  onSubmitted,
  compact = false,
  externalLimitPrice,
  onSideChange,
  showOrderBook = true,
  bookPollMs = 500,
  quoteBid,
  quoteAsk,
}: OrderTicketProps) {
  const queryClient = useQueryClient();
  const { user } = useAuth();
  const [riskConfirm, setRiskConfirm] = useState(false);
  const bookPollInterval = useVisiblePollInterval(bookPollMs);
  const [side, setSide] = useState<OrderSide>(prefill?.side ?? "buy");
  const [orderType, setOrderType] = useState<OrderType>("limit");
  const [quantity, setQuantity] = useState("");
  const [limitPrice, setLimitPrice] = useState("");
  const [stopPrice, setStopPrice] = useState("");
  const [ocoPrice, setOcoPrice] = useState("");
  const [trailPct, setTrailPct] = useState("2");
  const [tif, setTif] = useState<TimeInForce>("gtc");
  const [gtdDate, setGtdDate] = useState("");
  const [useBracket, setUseBracket] = useState(true);
  const [stopLoss, setStopLoss] = useState("");
  const [takeProfit, setTakeProfit] = useState("");
  const [positionHorizon, setPositionHorizon] = useState(prefill?.time_horizon ?? "1 day");
  const [positionExpiry, setPositionExpiry] = useState("");
  const [fatFingerPending, setFatFingerPending] = useState(false);

  useEffect(() => {
    if (!prefill) return;
    setSide(prefill.side);
    setQuantity(String(prefill.quantity));
    if (prefill.limit_price) setLimitPrice(String(prefill.limit_price));
    if (prefill.stop_loss) setStopLoss(String(prefill.stop_loss));
    if (prefill.take_profit) setTakeProfit(String(prefill.take_profit));
    setPositionHorizon(prefill.time_horizon || "1 day");
    if (prefill.expiry_at) {
      setPositionExpiry(prefill.expiry_at.slice(0, 16));
    }
    setUseBracket(Boolean(prefill.bracket));
  }, [prefill]);

  useEffect(() => {
    if (externalLimitPrice != null && Number.isFinite(externalLimitPrice)) {
      setLimitPrice(String(externalLimitPrice));
      if (orderType === "market") setOrderType("limit");
    }
  }, [externalLimitPrice, orderType]);

  const handleSide = (next: OrderSide) => {
    setSide(next);
    onSideChange?.(next);
  };

  const { data: book, isLoading: bookLoading } = useQuery({
    queryKey: ["order-book", ticker],
    queryFn: () => ordersApi.orderBook(ticker),
    enabled: Boolean(ticker) && showOrderBook,
    refetchInterval: bookPollInterval,
    staleTime: 250,
    placeholderData: (prev) => prev,
  });

  const { data: symbolRules } = useQuery({
    queryKey: ["symbol-rules", ticker],
    queryFn: () => ordersApi.symbolRules(ticker),
    enabled: Boolean(ticker),
    staleTime: 60_000,
  });

  const executionBlocked = symbolRules?.execution_block_type === "unavailable";
  const connectProviderBlocked = symbolRules?.execution_block_type === "connect_provider";
  const tradingBlocked =
    symbolRules?.data_only === true ||
    symbolRules?.execution_enabled === false;

  const hasBook = Boolean(book && (book.bids.length > 0 || book.asks.length > 0));

  const bestBid = quoteBid ?? book?.bids[0]?.price ?? null;
  const bestAsk = quoteAsk ?? book?.asks[0]?.price ?? null;

  const priceNum = parseFloat(limitPrice) || book?.mid_price || bestAsk || bestBid || 0;
  const qtyNum = parseFloat(quantity) || 0;
  const notional = priceNum * qtyNum;
  const crypto = /(-USD|USDT|USDC|BTC|ETH)$/i.test(ticker) && !/^[A-Z]{1,5}$/.test(ticker);
  const rubVenue = ["moex", "tinkoff", "tbank", "finam"].includes(String(symbolRules?.venue || "").toLowerCase());
  const cur = rubVenue || classifySymbol(ticker).currency === "RUB" ? "₽" : "$";
  const unitLabel = crypto ? "монет" : "шт. бумаг";
  const unitShort = crypto ? "монету" : "шт.";

  const { data: slippage } = useQuery({
    queryKey: ["slippage", ticker, notional],
    queryFn: () => ordersApi.slippage(ticker, notional),
    enabled: orderType === "market" && notional > 0,
  });

  const { data: gate } = useQuery({
    queryKey: ["risk-gate", user?.id, ticker, qtyNum, priceNum, riskConfirm],
    enabled: Boolean(user?.id) && qtyNum > 0,
    queryFn: () =>
      ordersApi.riskGatePreview({
        user_id: user?.id as string,
        ticker,
        qty: qtyNum,
        price: priceNum,
        confirmed: riskConfirm,
      }),
  });

  const applyPct = useCallback(
    (pct: number) => {
      const refPrice = priceNum || book?.mid_price || 1;
      const usd = (availableBalanceUsd * pct) / 100;
      setQuantity(String(Math.max(0, usd / refPrice).toFixed(6)));
    },
    [availableBalanceUsd, book?.mid_price, priceNum],
  );

  const validationHints = useMemo(() => {
    if (!symbolRules || qtyNum <= 0) return [];
    const hints: string[] = [];
    if (qtyNum < symbolRules.min_qty) {
      hints.push(`Min qty ${symbolRules.min_qty}`);
    }
    const step = symbolRules.lot_size;
    if (step > 0 && Math.abs(qtyNum / step - Math.round(qtyNum / step)) > 1e-6) {
      hints.push(`Qty step ${step}`);
    }
    if (priceNum > 0 && symbolRules.min_notional_usd && qtyNum * priceNum < symbolRules.min_notional_usd) {
      hints.push(`Min notional $${symbolRules.min_notional_usd}`);
    }
    return hints;
  }, [symbolRules, qtyNum, priceNum]);

  const submitMutation = useMutation({
    mutationFn: () =>
      ordersApi.submit({
        ticker,
        side,
        order_type: orderType,
        quantity: qtyNum,
        limit_price: orderType !== "market" ? parseFloat(limitPrice) || undefined : undefined,
        stop_price:
          orderType === "stop" || orderType === "stop_limit" || orderType === "trailing_stop"
            ? parseFloat(stopPrice) || undefined
            : undefined,
        time_in_force: tif,
        gtd_expires_at: tif === "gtd" && gtdDate ? new Date(gtdDate).toISOString() : undefined,
        trailing_stop_pct:
          orderType === "trailing_stop" ? parseFloat(trailPct) || undefined : undefined,
        oco_sibling_price: orderType === "oco" ? parseFloat(ocoPrice) || undefined : undefined,
        bracket:
          useBracket && (stopLoss || takeProfit)
            ? {
                stop_loss: parseFloat(stopLoss) || undefined,
                take_profit: parseFloat(takeProfit) || undefined,
              }
            : undefined,
        risk_confirm: riskConfirm,
        maneuver_id: prefill?.maneuver_id,
        position_time_horizon: positionHorizon.trim() || undefined,
        position_expiry_at: positionExpiry ? new Date(positionExpiry).toISOString() : undefined,
      }),
    onSuccess: (order) => {
      toast.success(`Order ${order.status}: ${order.ticker}`);
      queryClient.invalidateQueries({ queryKey: ["manual-orders"] });
      queryClient.invalidateQueries({ queryKey: ["portfolio-balances"] });
      onSubmitted?.(order);
    },
    onError: (err) => toast.error(extractErrorMessage(err, "Не удалось разместить ордер")),
  });

  const preview = useMemo(() => {
    const qty = parseFloat(quantity) || 0;
    if (qty <= 0) return null;
    const bids = book?.bids?.map((l) => ({ price: l.price, size: l.size })) ?? [];
    const asks = book?.asks?.map((l) => ({ price: l.price, size: l.size })) ?? [];
    const limit = parseFloat(limitPrice) || undefined;
    return estimateOrderPreview({
      side,
      orderType,
      quantity: qty,
      limitPrice: limit,
      bids,
      asks,
      availableBalanceUsd,
    });
  }, [side, orderType, quantity, limitPrice, book, availableBalanceUsd]);

  const estFees = useMemo(() => preview?.feeUsd ?? (notional > 0 ? notional * 0.001 : 0), [preview, notional]);

  const needsFatFingerConfirm =
    notional >= FAT_FINGER_NOTIONAL_USD ||
    (availableBalanceUsd > 0 && notional >= availableBalanceUsd * FAT_FINGER_BALANCE_FRACTION);

  useEffect(() => {
    setFatFingerPending(false);
  }, [ticker, quantity, limitPrice, orderType, side]);

  const handleSubmit = () => {
    if (needsFatFingerConfirm && !fatFingerPending) {
      setFatFingerPending(true);
      return;
    }
    submitMutation.mutate();
  };

  if (symbolRules && executionBlocked) {
    return (
      <div
        className={clsx(
          "rounded-lg border border-qa-accent-border bg-qa-active text-qa-text",
          compact ? "p-3 text-xs" : "p-4 text-sm",
        )}
      >
        <div className="flex items-start gap-2 text-qa-warning">
          <AlertTriangle size={16} className="shrink-0 mt-0.5" />
          <div>
            <p className="font-semibold text-sm">Торговля недоступна</p>
            <p className="text-qa-muted mt-1">
              {symbolRules.feed_label_ru ?? "Торговля этого инструмента сейчас недоступна."}
            </p>
          </div>
        </div>
      </div>
    );
  }

  if (symbolRules && connectProviderBlocked) {
    const providers = symbolRules.required_providers_ru?.join(", ");
    return (
      <div
        className={clsx(
          "rounded-lg border border-qa-accent-border bg-qa-active text-qa-text",
          compact ? "p-3 text-xs" : "p-4 text-sm",
        )}
      >
        <div className="flex items-start gap-2 text-qa-warning">
          <AlertTriangle size={16} className="shrink-0 mt-0.5" />
          <div>
            <p className="font-semibold text-sm">Требуется подключение брокера</p>
            <p className="text-qa-muted mt-1">
              {symbolRules.feed_label_ru ??
                (providers
                  ? `Подключите ${providers} для торговли этим инструментом.`
                  : "Подключите брокера для торговли этим инструментом.")}
            </p>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div
      className={clsx(
        "rounded-lg border border-qa-border bg-qa-panel text-qa-text",
        compact ? "p-3 text-xs" : "p-4 text-sm",
      )}
    >
      <OrderMarginNote />
      <div className="flex gap-2 mb-3">
        <button
          type="button"
          onClick={() => handleSide("buy")}
          className={clsx(
            "flex-1 py-2 rounded-md font-bold",
            side === "buy"
              ? "bg-terminal-up/20 text-terminal-up border border-terminal-up/40"
              : "bg-qa-panel-secondary",
          )}
        >
          Купить
        </button>
        <button
          type="button"
          onClick={() => handleSide("sell")}
          className={clsx(
            "flex-1 py-2 rounded-md font-bold",
            side === "sell"
              ? "bg-terminal-down/20 text-terminal-down border border-terminal-down/40"
              : "bg-qa-panel-secondary",
          )}
        >
          Продать
        </button>
      </div>

      <div className="flex flex-wrap gap-1 mb-3">
        {ORDER_TYPES.map((t) => (
          <button
            key={t.value}
            type="button"
            onClick={() => setOrderType(t.value)}
            className={clsx(
              "px-2 py-1 text-[10px] rounded border",
              orderType === t.value
                ? "border-terminal-accent/50 text-terminal-accent bg-[var(--qa-active)]"
                : "border-qa-border bg-qa-panel-secondary text-qa-muted hover:bg-[var(--qa-hover)]",
            )}
          >
            {t.label}
          </button>
        ))}
      </div>

      <div className="grid grid-cols-2 gap-2 mb-2">
        <label className="block">
          <span className="text-qa-muted text-[11px]">
            {side === "buy" ? "Сколько купить" : "Сколько продать"}, {unitLabel}
          </span>
          <input
            type="number"
            value={quantity}
            onChange={(e) => setQuantity(e.target.value)}
            className="w-full mt-1 bg-qa-panel-secondary border border-qa-border rounded px-2 py-1.5"
          />
        </label>
        <label className="block">
          <span className="text-qa-muted text-[11px]">
            {orderType === "market" ? "Цена — лучшая на рынке" : `Цена за 1 ${unitShort}, ${cur}`}
          </span>
          <input
            type="number"
            value={limitPrice}
            disabled={orderType === "market"}
            onChange={(e) => setLimitPrice(e.target.value)}
            className="w-full mt-1 bg-qa-panel-secondary border border-qa-border rounded px-2 py-1.5 disabled:opacity-50"
          />
        </label>
      </div>

      <div className="flex flex-wrap gap-1 mb-2">
        {PCT_BUTTONS.map((p) => (
          <button
            key={p}
            type="button"
            onClick={() => applyPct(p)}
            className="px-2 py-0.5 text-[10px] rounded bg-qa-panel-secondary border border-qa-border hover:bg-[var(--qa-hover)]"
          >
            {p}%
          </button>
        ))}
        {bestBid != null && (
          <button
            type="button"
            onClick={() => {
              setLimitPrice(String(bestBid));
              if (orderType === "market") setOrderType("limit");
            }}
            className="px-2 py-0.5 text-[10px] rounded border border-terminal-up/30 text-terminal-up hover:bg-terminal-up/10"
          >
            Лучший спрос {bestBid}
          </button>
        )}
        {bestAsk != null && (
          <button
            type="button"
            onClick={() => {
              setLimitPrice(String(bestAsk));
              if (orderType === "market") setOrderType("limit");
            }}
            className="px-2 py-0.5 text-[10px] rounded border border-terminal-down/30 text-terminal-down hover:bg-terminal-down/10"
          >
            Лучшее предложение {bestAsk}
          </button>
        )}
      </div>

      {(orderType === "stop" || orderType === "stop_limit" || orderType === "trailing_stop") && (
        <label className="block mb-2">
          <span className="text-qa-muted text-[11px]">Сработает, когда цена дойдёт до</span>
          <input
            type="number"
            value={stopPrice}
            onChange={(e) => setStopPrice(e.target.value)}
            className="w-full mt-1 bg-qa-panel-secondary border border-qa-border rounded px-2 py-1.5"
          />
        </label>
      )}

      {orderType === "oco" && (
        <label className="block mb-2">
          <span className="text-qa-muted text-[11px]">Вторая цена (исполнится одна из двух)</span>
          <input
            type="number"
            value={ocoPrice}
            onChange={(e) => setOcoPrice(e.target.value)}
            className="w-full mt-1 bg-qa-panel-secondary border border-qa-border rounded px-2 py-1.5"
          />
        </label>
      )}

      {orderType === "trailing_stop" && (
        <label className="block mb-2">
          <span className="text-qa-muted text-[11px]">Отставание стопа от цены, %</span>
          <input
            type="number"
            value={trailPct}
            onChange={(e) => setTrailPct(e.target.value)}
            className="w-full mt-1 bg-qa-panel-secondary border border-qa-border rounded px-2 py-1.5"
          />
        </label>
      )}

      <label className="block mb-2">
        <span className="text-qa-muted text-[11px]">Сколько действует заявка</span>
        <select
          value={tif}
          onChange={(e) => setTif(e.target.value as TimeInForce)}
          className="w-full mt-1 bg-qa-panel-secondary border border-qa-border rounded px-2 py-1.5"
        >
          {TIF_OPTIONS.map((t) => (
            <option key={t.value} value={t.value}>
              {t.label}
            </option>
          ))}
        </select>
      </label>

      {tif === "gtd" && (
        <label className="block mb-2">
          <span className="text-qa-muted text-[11px]">Действует до</span>
          <input
            type="datetime-local"
            value={gtdDate}
            onChange={(e) => setGtdDate(e.target.value)}
            className="w-full mt-1 bg-qa-panel-secondary border border-qa-border rounded px-2 py-1.5"
          />
        </label>
      )}

      <div className="mb-3 p-2 rounded border border-qa-border bg-qa-panel-secondary/50">
        <label className="flex items-center gap-2 text-xs mb-2">
          <input type="checkbox" checked={useBracket} onChange={(e) => setUseBracket(e.target.checked)} />
          Сразу поставить стоп-лосс и тейк-профит
        </label>
        {useBracket && (
          <div className="grid grid-cols-2 gap-2">
            <input
              placeholder="Стоп-лосс (цена)"
              type="number"
              value={stopLoss}
              onChange={(e) => setStopLoss(e.target.value)}
              className="bg-qa-panel border border-qa-border rounded px-2 py-1 text-xs"
            />
            <input
              placeholder="Тейк-профит (цена)"
              type="number"
              value={takeProfit}
              onChange={(e) => setTakeProfit(e.target.value)}
              className="bg-qa-panel border border-qa-border rounded px-2 py-1 text-xs"
            />
          </div>
        )}
      </div>

      {showOrderBook && (
        <div className="mb-3">
          {bookLoading && !book ? (
            <div className="text-xs text-qa-muted flex items-center gap-2 py-4 justify-center">
              <Loader2 size={14} className="animate-spin" /> Загрузка стакана…
            </div>
          ) : hasBook ? (
            <OrderBookDepth
              book={book!}
              limitPrice={parseFloat(limitPrice) || undefined}
              side={side}
            />
          ) : (
            <p className="text-xs text-center py-4 text-qa-warning">нет данных</p>
          )}
        </div>
      )}

      <div className="mb-3 p-2 rounded border border-terminal-accent/25 bg-terminal-accent/5">
        <div className="flex items-center justify-between gap-2 mb-2">
          <span className="text-qa-muted text-[11px]">Сколько держать позицию</span>
          <span className="text-[10px] text-terminal-accent">
            {positionExpiry ? "до точной даты" : formatDurationHorizonLabel(positionHorizon) || "не задано"}
          </span>
        </div>
        <div className="flex flex-wrap gap-1 mb-2">
          {POSITION_DURATION_PRESETS.map((preset) => (
            <button
              key={preset.key}
              type="button"
              onClick={() => {
                setPositionHorizon(preset.api);
                setPositionExpiry("");
              }}
              className={clsx(
                "px-2 py-0.5 text-[10px] rounded border",
                positionHorizon === preset.api && !positionExpiry
                  ? "border-terminal-accent/60 text-terminal-accent bg-[var(--qa-active)]"
                  : "border-qa-border text-qa-muted bg-qa-panel-secondary",
              )}
            >
              {preset.label}
            </button>
          ))}
        </div>
        <div className="grid grid-cols-2 gap-2">
          <input
            placeholder="например, 6 часов или 3 дня"
            value={positionHorizon}
            onChange={(e) => setPositionHorizon(e.target.value)}
            className="bg-qa-panel border border-qa-border rounded px-2 py-1 text-xs"
          />
          <input
            type="datetime-local"
            value={positionExpiry}
            onChange={(e) => setPositionExpiry(e.target.value)}
            className="bg-qa-panel border border-qa-border rounded px-2 py-1 text-xs"
            title="Точная дата закрытия (необязательно)"
          />
        </div>
      </div>

      <div className="mb-3 text-[11px] text-qa-muted space-y-0.5">
        <div>Сумма сделки ≈ {notional.toLocaleString("ru-RU", { maximumFractionDigits: 2 })} {cur}</div>
        <div>Комиссия ≈ {estFees.toLocaleString("ru-RU", { maximumFractionDigits: 2 })} {cur}</div>
        {symbolRules && (
          <div>
            Площадка {symbolRules.venue.toUpperCase()} · шаг цены {symbolRules.tick_size} · лот {symbolRules.lot_size}
          </div>
        )}
        {validationHints.map((hint) => (
          <div key={hint} className="text-qa-warning">
            {hint}
          </div>
        ))}
        {prefill?.position_pct != null && (
          <div>Рекомендуемый размер: {prefill.position_pct.toFixed(2)}% портфеля</div>
        )}
        {slippage?.warning && (
          <div className="flex items-start gap-1 text-qa-warning">
            <AlertTriangle size={12} className="mt-0.5 shrink-0" />
            {slippage.warning}
          </div>
        )}
      </div>

      {preview && (
        <OrderConfirmSummary
          ticker={ticker}
          side={side}
          preview={preview}
          confirmArmed={fatFingerPending}
        />
      )}

      {fatFingerPending && (
        <div className="mb-3 p-3 rounded border border-qa-accent-border bg-qa-active text-xs space-y-2">
          <div className="flex items-start gap-2 text-qa-warning">
            <AlertTriangle size={14} className="shrink-0 mt-0.5" />
            <div>
              <p className="font-semibold">Подтвердите крупную заявку</p>
              <p className="text-qa-muted mt-1">
                Сумма {notional.toLocaleString("ru-RU", { maximumFractionDigits: 0 })} {cur} — нажмите ещё раз, чтобы отправить.
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={() => setFatFingerPending(false)}
            className="text-[10px] text-qa-muted hover:text-qa-text underline"
          >
            Отмена
          </button>
        </div>
      )}

      {tradingBlocked && (
        <div className="mb-3 p-3 rounded border border-qa-accent-border bg-qa-active text-xs text-qa-warning">
          <div className="flex items-start gap-2">
            <AlertTriangle size={14} className="shrink-0 mt-0.5" />
            <div>
              <p className="font-semibold">
                {symbolRules?.execution_block_type === "connect_provider"
                  ? "Требуется подключение брокера"
                  : symbolRules?.data_only
                    ? "Только данные — торговля недоступна"
                    : "Торговля недоступна"}
              </p>
              <p className="text-qa-muted mt-1">
                {symbolRules?.feed_label_ru ??
                  (symbolRules?.data_only
                    ? "данные на конец предыдущего торгового дня"
                    : "Торговля этого инструмента сейчас недоступна.")}
              </p>
            </div>
          </div>
        </div>
      )}

      <PretradeImpact ticker={ticker} side={side} qty={qtyNum} price={priceNum} />

      {gate ? (
        <div className="mb-3 p-3 rounded border border-qa-accent-border text-xs">
          <p className="uppercase tracking-wide text-qa-muted">Проверка риска</p>
          <p className="mt-1 text-qa-text">{explainGate(gate)}</p>
          {gate.requires_confirm ? (
            <label className="mt-2 flex items-center gap-2 text-qa-warning">
              <input type="checkbox" checked={riskConfirm} onChange={(e) => setRiskConfirm(e.target.checked)} />
              Подтверждаю предупреждение (решение за мной)
            </label>
          ) : null}
        </div>
      ) : null}

      <button
        type="button"
        disabled={
          tradingBlocked ||
          submitMutation.isPending ||
          qtyNum <= 0 ||
          validationHints.length > 0 ||
          gate?.verdict === "block" ||
          (gate?.requires_confirm && !riskConfirm)
        }
        onClick={handleSubmit}
        className={clsx(
          "w-full py-2 rounded-md font-bold disabled:opacity-50",
          side === "buy" ? "btn-success" : "btn-danger-solid",
          fatFingerPending && "ring-2 ring-terminal-accent/60",
        )}
      >
        {submitMutation.isPending ? (
          <span className="inline-flex items-center gap-2 justify-center">
            <Loader2 size={14} className="animate-spin" /> Отправляем…
          </span>
        ) : fatFingerPending ? (
          `Подтвердить: ${side === "buy" ? "купить" : "продать"} на ${notional.toLocaleString("ru-RU", { maximumFractionDigits: 0 })} ${cur}`
        ) : tradingBlocked ? (
          "Торговля недоступна"
        ) : (
          `${side === "buy" ? "Купить" : "Продать"} ${ticker}`
        )}
      </button>
    </div>
  );
}
