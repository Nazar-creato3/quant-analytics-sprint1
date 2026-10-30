"""MEXC spot / tokenized equities execution provider."""
from __future__ import annotations

import hashlib
import hmac
import time
import uuid
from datetime import datetime, timezone
from typing import Any, AsyncIterator
from urllib.parse import urlencode

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
_RECV_WINDOW = 5000


class MexcTokenizedEquityProvider:
    """Spot/tokenized US equities on MEXC via v3 REST API."""

    kind = ProviderKind.MEXC_TOKENIZED

    def __init__(
        self,
        *,
        api_key: str,
        api_secret: str,
        base_url: str | None = None,
    ) -> None:
        self._api_key = api_key.strip()
        self._api_secret = api_secret.strip()
        self._base_url = (
            base_url or getattr(settings, "MEXC_API_BASE_URL", None) or "https://api.mexc.com"
        ).rstrip("/")

    def _sign(self, params: dict[str, Any]) -> dict[str, Any]:
        signed = dict(params)
        signed["timestamp"] = int(time.time() * 1000)
        signed["recvWindow"] = _RECV_WINDOW
        query = urlencode(sorted((k, str(v)) for k, v in signed.items()))
        sig = hmac.new(self._api_secret.encode(), query.encode(), hashlib.sha256).hexdigest()
        signed["signature"] = sig
        return signed

    def _headers(self) -> dict[str, str]:
        return {"X-MEXC-APIKEY": self._api_key, "Content-Type": "application/x-www-form-urlencoded"}

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any] | list[Any]:
        signed = self._sign(params or {})
        url = f"{self._base_url}{path}"
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            if method.upper() == "GET":
                resp = await client.get(url, params=signed, headers=self._headers())
            elif method.upper() == "POST":
                resp = await client.post(url, data=signed, headers=self._headers())
            elif method.upper() == "DELETE":
                resp = await client.delete(url, params=signed, headers=self._headers())
            else:
                raise ValueError(f"Unsupported method {method}")
        data = resp.json()
        if resp.status_code >= 400 or (isinstance(data, dict) and data.get("code") not in (None, 0, "0", 200)):
            msg = data.get("msg") if isinstance(data, dict) else resp.text[:300]
            raise RuntimeError(f"MEXC API error: {msg or resp.status_code}")
        return data

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
                provider=ProviderKind.MEXC_TOKENIZED,
                account_display=f"MEXC Spot (${bal.total_usd:,.2f})",
                meta={"total_usd": bal.total_usd},
            )
        except Exception as exc:  # noqa: BLE001
            return ConnectionResult(ok=False, provider=ProviderKind.MEXC_TOKENIZED, error=str(exc))

    async def get_account_balance(self) -> AccountBalance:
        result = await self._request("GET", "/api/v3/account")
        assert isinstance(result, dict)
        now = datetime.now(timezone.utc)
        balances: list[Balance] = []
        total_usd = 0.0
        stables = {"USDT", "USDC", "USD", "BUSD", "FDUSD"}
        for row in result.get("balances") or []:
            ccy = str(row.get("asset", "")).upper()
            free = float(row.get("free") or 0)
            locked = float(row.get("locked") or 0)
            total = free + locked
            if total <= 0:
                continue
            usd = total if ccy in stables else total  # mark price filled later for tokens
            balances.append(
                Balance(currency=ccy, free=free, locked=locked, total=total, usd_value=usd)
            )
            if ccy in stables:
                total_usd += total
        if not balances:
            balances.append(Balance(currency="USDT", free=0.0, locked=0.0, total=0.0, usd_value=0.0))
        return AccountBalance(
            balances=balances,
            total_usd=round(total_usd, 2),
            as_of=now,
            mode="live",
            source="mexc_tokenized",
        )

    async def get_positions(self) -> list[Position]:
        bal = await self.get_account_balance()
        positions: list[Position] = []
        stables = {"USDT", "USDC", "USD", "BUSD", "FDUSD"}
        for b in bal.balances:
            if b.currency in stables or b.total <= 0:
                continue
            ui = b.currency.replace("USDT", "").rstrip("X")
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
        route = resolve_symbol_route(symbol, provider_type="mexc")
        exec_sym = route.execution_provider_ticker
        params: dict[str, Any] = {
            "symbol": exec_sym,
            "side": side.upper(),
            "type": "MARKET" if order_type == "market" else "LIMIT",
            "quantity": str(qty),
        }
        if client_order_id:
            params["newClientOrderId"] = client_order_id
        if order_type == "limit" and price:
            params["price"] = str(price)
        try:
            result = await self._request("POST", "/api/v3/order", params=params)
            assert isinstance(result, dict)
            order_id = str(result.get("orderId") or "")
            now = datetime.now(timezone.utc)
            filled_raw = result.get("executedQty")
            if filled_raw in (None, ""):
                filled_qty = 0.0
            else:
                try:
                    filled_qty = float(filled_raw)
                except (TypeError, ValueError):
                    return OrderResult(ok=False, error="нет данных")
            order = ProviderOrder(
                id=order_id,
                client_order_id=client_order_id,
                symbol=route.ui_symbol,
                execution_symbol=exec_sym,
                side=side,
                order_type=order_type,
                qty=qty,
                price=price,
                status="submitted",
                filled_qty=filled_qty,
                filled_price=float(result["price"]) if result.get("price") else None,
                submitted_at=now,
                raw=result,
            )
            return OrderResult(ok=True, order=order)
        except Exception as exc:  # noqa: BLE001
            logger.warning("MEXC order failed", symbol=symbol, error=str(exc))
            return OrderResult(ok=False, error=str(exc))

    async def cancel_order(self, order_id: str) -> CancelResult:
        try:
            await self._request(
                "DELETE",
                "/api/v3/order",
                params={"symbol": "", "orderId": order_id},
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
        if not symbol:
            return []
        exec_sym = execution_ticker_for(symbol, provider_type="mexc")
        result = await self._request(
            "GET",
            "/api/v3/allOrders",
            params={"symbol": exec_sym, "limit": min(limit, 500)},
        )
        orders: list[ProviderOrder] = []
        if not isinstance(result, list):
            return orders
        for row in result[:limit]:
            qty_raw = row.get("origQty")
            time_raw = row.get("time")
            if qty_raw in (None, "") or time_raw in (None, ""):
                logger.warning("MEXC order history row skipped: нет данных")
                continue
            try:
                qty = float(qty_raw)
                submitted_ms = int(time_raw)
            except (TypeError, ValueError):
                logger.warning("MEXC order history row skipped: нет данных")
                continue
            if qty <= 0:
                logger.warning("MEXC order history row skipped: нет данных")
                continue
            filled_raw = row.get("executedQty")
            if filled_raw in (None, ""):
                filled_qty = 0.0 if str(row.get("status", "")).upper() != "FILLED" else None
            else:
                try:
                    filled_qty = float(filled_raw)
                except (TypeError, ValueError):
                    filled_qty = None
            if filled_qty is None:
                logger.warning("MEXC order history row skipped: нет данных")
                continue
            sym = str(row.get("symbol", ""))
            ui = sym.replace("USDT", "").rstrip("X")
            status_raw = str(row.get("status", "")).upper()
            status = "filled" if status_raw == "FILLED" else "submitted"
            orders.append(
                ProviderOrder(
                    id=str(row.get("orderId", "")),
                    client_order_id=row.get("clientOrderId"),
                    symbol=ui,
                    execution_symbol=sym,
                    side=str(row.get("side", "")).lower(),  # type: ignore[arg-type]
                    order_type="market" if row.get("type") == "MARKET" else "limit",
                    qty=qty,
                    price=float(row["price"]) if row.get("price") else None,
                    status=status,  # type: ignore[arg-type]
                    filled_qty=filled_qty,
                    filled_price=None,
                    submitted_at=datetime.fromtimestamp(
                        submitted_ms / 1000, tz=timezone.utc
                    ),
                    raw=row,
                )
            )
        return orders

    async def stream_prices(self, symbols: list[str]) -> AsyncIterator[PriceTick]:
        import asyncio

        while True:
            now = datetime.now(timezone.utc)
            for sym in symbols:
                exec_sym = execution_ticker_for(sym, provider_type="mexc")
                try:
                    result = await self._request(
                        "GET",
                        "/api/v3/ticker/price",
                        params={"symbol": exec_sym},
                    )
                    if isinstance(result, dict):
                        price_raw = result.get("price")
                        if price_raw in (None, ""):
                            continue
                        try:
                            px = float(price_raw)
                        except (TypeError, ValueError):
                            continue
                        if px > 0:
                            route = resolve_symbol_route(sym, provider_type="mexc")
                            yield PriceTick(
                                symbol=route.ui_symbol,
                                execution_symbol=exec_sym,
                                price=px,
                                ts=now,
                            )
                except Exception as exc:  # noqa: BLE001
                    logger.debug("MEXC ticker poll failed", symbol=sym, error=str(exc))
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
