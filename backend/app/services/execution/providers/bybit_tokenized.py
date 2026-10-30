"""Bybit v5 tokenized equities execution provider (Task 2)."""
from __future__ import annotations

import hashlib
import hmac
import json
import time
import uuid
from datetime import datetime, timezone
from typing import Any, AsyncIterator

import httpx

from app.core.config import settings
from app.core.logging import get_logger
from app.services.execution.providers.types import (
    AccountBalance,
    Balance,
    CancelResult,
    ConnectionResult,
    OrderResult,
    OrderSide,
    OrderType,
    Position,
    PositionUpdate,
    PriceTick,
    ProviderKind,
    ProviderOrder,
)
from app.services.execution.symbol_mapping import execution_ticker_for, resolve_symbol_route

logger = get_logger(__name__)
_TIMEOUT = httpx.Timeout(15.0, connect=5.0)
_RECV_WINDOW = "5000"


class BybitTokenizedEquityProvider:
    """Spot/tokenized US equities on Bybit via v5 REST API."""

    kind = ProviderKind.BYBIT_TOKENIZED

    def __init__(
        self,
        *,
        api_key: str,
        api_secret: str,
        base_url: str | None = None,
    ) -> None:
        self._api_key = api_key.strip()
        self._api_secret = api_secret.strip()
        self._base_url = (base_url or getattr(settings, "BYBIT_API_BASE_URL", None) or "https://api.bybit.com").rstrip("/")
        self._connected = False

    def _sign(self, payload: str, timestamp: str) -> str:
        param_str = f"{timestamp}{self._api_key}{_RECV_WINDOW}{payload}"
        return hmac.new(self._api_secret.encode(), param_str.encode(), hashlib.sha256).hexdigest()

    def _headers(self, sign: str, timestamp: str) -> dict[str, str]:
        return {
            "X-BAPI-API-KEY": self._api_key,
            "X-BAPI-SIGN": sign,
            "X-BAPI-TIMESTAMP": timestamp,
            "X-BAPI-RECV-WINDOW": _RECV_WINDOW,
            "Content-Type": "application/json",
        }

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        params = params or {}
        query = "&".join(f"{k}={v}" for k, v in sorted(params.items()) if v is not None)
        timestamp = str(int(time.time() * 1000))
        if method.upper() in ("GET", "DELETE"):
            payload = query
        else:
            payload = json.dumps(body or {}, separators=(",", ":"))
        sign = self._sign(payload, timestamp)
        headers = self._headers(sign, timestamp)
        url = f"{self._base_url}{path}"
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            if method.upper() == "GET":
                resp = await client.get(url, params=params, headers=headers)
            elif method.upper() == "POST":
                resp = await client.post(url, content=payload, headers=headers)
            else:
                raise ValueError(f"Unsupported method {method}")
        data = resp.json()
        if resp.status_code >= 400 or int(data.get("retCode", 0)) != 0:
            msg = data.get("retMsg") or resp.text[:300]
            raise RuntimeError(f"Bybit API error: {msg}")
        return data.get("result") or {}

    async def connect(self, credentials: dict[str, Any]) -> ConnectionResult:
        if credentials.get("api_key"):
            self._api_key = credentials["api_key"].strip()
        if credentials.get("api_secret"):
            self._api_secret = credentials["api_secret"].strip()
        if credentials.get("base_url"):
            self._base_url = credentials["base_url"].rstrip("/")
        try:
            bal = await self.get_account_balance()
            self._connected = True
            return ConnectionResult(
                ok=True,
                provider=ProviderKind.BYBIT_TOKENIZED,
                account_display=f"Bybit Unified (${bal.total_usd:,.2f})",
                meta={"total_usd": bal.total_usd},
            )
        except Exception as exc:  # noqa: BLE001
            return ConnectionResult(ok=False, provider=ProviderKind.BYBIT_TOKENIZED, error=str(exc))

    async def get_account_balance(self) -> AccountBalance:
        result = await self._request("GET", "/v5/account/wallet-balance", params={"accountType": "UNIFIED"})
        now = datetime.now(timezone.utc)
        balances: list[Balance] = []
        total_usd = 0.0
        for acct in result.get("list") or []:
            for coin in acct.get("coin") or []:
                ccy = str(coin.get("coin", "")).upper()
                wallet = float(coin.get("walletBalance") or 0)
                locked = float(coin.get("locked") or 0)
                usd_val = float(coin.get("usdValue") or wallet)
                if wallet <= 0 and locked <= 0:
                    continue
                balances.append(
                    Balance(
                        currency=ccy,
                        free=round(wallet - locked, 8),
                        locked=round(locked, 8),
                        total=round(wallet, 8),
                        usd_value=round(usd_val, 2),
                    )
                )
                total_usd += usd_val
        if not balances:
            balances.append(Balance(currency="USD", free=0.0, locked=0.0, total=0.0, usd_value=0.0))
        return AccountBalance(
            balances=balances,
            total_usd=round(total_usd, 2),
            as_of=now,
            mode="live",
            source="bybit_tokenized",
        )

    async def get_positions(self) -> list[Position]:
        bal = await self.get_account_balance()
        positions: list[Position] = []
        for b in bal.balances:
            if b.currency in ("USDT", "USDC", "USD", "BUSD"):
                continue
            if b.total <= 0:
                continue
            ui = b.currency.rstrip("X") if b.currency.endswith("X") else b.currency
            positions.append(
                Position(
                    symbol=ui,
                    execution_symbol=b.currency,
                    qty=b.total,
                    avg_entry_price=None,
                    mark_price=(b.usd_value / b.total) if b.total and b.usd_value else None,
                    unrealized_pnl_usd=None,
                )
            )
        return positions

    async def place_order(
        self,
        symbol: str,
        side: OrderSide,
        qty: float,
        order_type: OrderType = "market",
        price: float | None = None,
        *,
        client_order_id: str | None = None,
    ) -> OrderResult:
        route = resolve_symbol_route(symbol)
        exec_sym = route.execution_provider_ticker
        body: dict[str, Any] = {
            "category": "spot",
            "symbol": exec_sym,
            "side": side.capitalize(),
            "orderType": "Market" if order_type == "market" else "Limit",
            "qty": str(qty),
            "orderLinkId": client_order_id or f"apex-{uuid.uuid4().hex[:16]}",
        }
        if order_type == "limit" and price:
            body["price"] = str(price)
        try:
            result = await self._request("POST", "/v5/order/create", body=body)
            order_id = str(result.get("orderId") or "")
            now = datetime.now(timezone.utc)
            order = ProviderOrder(
                id=order_id,
                client_order_id=body["orderLinkId"],
                symbol=route.ui_symbol,
                execution_symbol=exec_sym,
                side=side,
                order_type=order_type,
                qty=qty,
                price=price,
                status="submitted",
                filled_qty=0.0,
                filled_price=None,
                submitted_at=now,
                raw=result,
            )
            return OrderResult(ok=True, order=order)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Bybit order failed", symbol=symbol, error=str(exc))
            return OrderResult(ok=False, error=str(exc))

    async def cancel_order(self, order_id: str) -> CancelResult:
        try:
            await self._request(
                "POST",
                "/v5/order/cancel",
                body={"category": "spot", "orderId": order_id},
            )
            return CancelResult(ok=True, order_id=order_id)
        except Exception as exc:  # noqa: BLE001
            return CancelResult(ok=False, order_id=order_id, error=str(exc))

    async def get_order_history(
        self,
        *,
        symbol: str | None = None,
        limit: int = 50,
    ) -> list[ProviderOrder]:
        params: dict[str, Any] = {"category": "spot", "limit": min(limit, 50)}
        if symbol:
            params["symbol"] = execution_ticker_for(symbol)
        result = await self._request("GET", "/v5/order/history", params=params)
        orders: list[ProviderOrder] = []
        for row in result.get("list") or []:
            qty_raw = row.get("qty")
            created_raw = row.get("createdTime")
            if qty_raw in (None, "") or created_raw in (None, ""):
                logger.warning("Bybit order history row skipped: нет данных")
                continue
            try:
                qty = float(qty_raw)
                created_ms = int(created_raw)
            except (TypeError, ValueError):
                logger.warning("Bybit order history row skipped: нет данных")
                continue
            if qty <= 0:
                logger.warning("Bybit order history row skipped: нет данных")
                continue
            filled_raw = row.get("cumExecQty")
            if filled_raw in (None, ""):
                filled_qty = 0.0 if str(row.get("orderStatus", "")).lower() != "filled" else None
            else:
                try:
                    filled_qty = float(filled_raw)
                except (TypeError, ValueError):
                    filled_qty = None
            if filled_qty is None:
                logger.warning("Bybit order history row skipped: нет данных")
                continue
            sym = str(row.get("symbol", ""))
            ui = sym.rstrip("X") if sym.endswith("X") else sym
            status_raw = str(row.get("orderStatus", "")).lower()
            status = "filled" if status_raw == "filled" else "submitted"
            orders.append(
                ProviderOrder(
                    id=str(row.get("orderId", "")),
                    client_order_id=row.get("orderLinkId"),
                    symbol=ui,
                    execution_symbol=sym,
                    side=str(row.get("side", "")).lower(),  # type: ignore[arg-type]
                    order_type="market" if row.get("orderType") == "Market" else "limit",
                    qty=qty,
                    price=float(row["price"]) if row.get("price") else None,
                    status=status,  # type: ignore[arg-type]
                    filled_qty=filled_qty,
                    filled_price=float(row["avgPrice"]) if row.get("avgPrice") else None,
                    submitted_at=datetime.fromtimestamp(created_ms / 1000, tz=timezone.utc),
                    raw=row,
                )
            )
        return orders

    async def stream_prices(self, symbols: list[str]) -> AsyncIterator[PriceTick]:
        import asyncio

        while True:
            now = datetime.now(timezone.utc)
            for sym in symbols:
                exec_sym = execution_ticker_for(sym)
                try:
                    result = await self._request(
                        "GET",
                        "/v5/market/tickers",
                        params={"category": "spot", "symbol": exec_sym},
                    )
                    rows = result.get("list") or []
                    if rows:
                        last_raw = rows[0].get("lastPrice")
                        if last_raw in (None, ""):
                            continue
                        try:
                            px = float(last_raw)
                        except (TypeError, ValueError):
                            continue
                        if px > 0:
                            route = resolve_symbol_route(sym)
                            yield PriceTick(
                                symbol=route.ui_symbol,
                                execution_symbol=exec_sym,
                                price=px,
                                ts=now,
                            )
                except Exception as exc:  # noqa: BLE001
                    logger.debug("Bybit ticker poll failed", symbol=sym, error=str(exc))
            await asyncio.sleep(2.0)

    async def stream_position_updates(self) -> AsyncIterator[PositionUpdate]:
        import asyncio

        while True:
            now = datetime.now(timezone.utc)
            for p in await self.get_positions():
                yield PositionUpdate(
                    symbol=p.symbol,
                    execution_symbol=p.execution_symbol,
                    qty=p.qty,
                    mark_price=p.mark_price,
                    ts=now,
                )
            await asyncio.sleep(10.0)
