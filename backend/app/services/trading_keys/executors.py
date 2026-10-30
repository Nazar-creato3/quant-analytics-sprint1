"""User-scoped Binance spot execution (Flow B)."""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import time
import uuid
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlencode

import httpx

from app.core.logging import get_logger
from app.services.execution.adapter import OrderRequest, OrderResult
from app.services.execution.guard import _guard_broker_submission
from app.services.market_data.binance_spot import ticker_to_binance_symbol
from app.services.trading_keys.binance_qty import binance_order_qty_params

logger = get_logger(__name__)
_TIMEOUT = httpx.Timeout(15.0, connect=5.0)


class BinanceUserExecutor:
    def __init__(
        self,
        *,
        api_key: str,
        api_secret: str,
        base_url: str | None = None,
        account_mode: str = "live",
    ) -> None:
        self._api_key = api_key
        self._api_secret = api_secret
        self._base = (base_url or (
            "https://testnet.binance.vision" if account_mode == "paper" else "https://api.binance.com"
        )).rstrip("/")

    async def _signed_post(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            ts_resp = await client.get(f"{self._base}/api/v3/time")
            ts_resp.raise_for_status()
            params["timestamp"] = int(ts_resp.json()["serverTime"])
            params["recvWindow"] = 60000
            query = urlencode(params)
            sig = hmac.new(self._api_secret.encode(), query.encode(), hashlib.sha256).hexdigest()
            signed = {**params, "signature": sig}
            resp = await client.post(
                f"{self._base}{path}",
                params=signed,
                headers={"X-MBX-APIKEY": self._api_key},
            )
            resp.raise_for_status()
            return resp.json()

    async def submit_order(self, req: OrderRequest) -> OrderResult:
        _guard_broker_submission(req)
        now = datetime.now(timezone.utc)
        symbol = ticker_to_binance_symbol(req.ticker)
        side = req.side.upper()
        otype = "MARKET" if req.order_type == "market" else req.order_type.upper()
        params: dict[str, Any] = {
            "symbol": symbol,
            "side": side,
            "type": otype,
            "newClientOrderId": req.client_order_id or f"apex-{uuid.uuid4().hex[:16]}",
        }
        if otype == "LIMIT" and req.limit_price:
            params["price"] = str(round(req.limit_price, 8))
            params["timeInForce"] = req.time_in_force.upper() if req.time_in_force else "GTC"
        try:
            params.update(binance_order_qty_params(req.qty, req.limit_price))
        except ValueError as exc:
            return OrderResult(
                broker_order_id=None,
                status="rejected",
                filled_price=None,
                filled_qty=None,
                submitted_at=now,
                error=str(exc),
            )

        try:
            raw = await self._signed_post("/api/v3/order", params)
            status = str(raw.get("status", "NEW")).lower()
            filled_qty = float(raw.get("executedQty") or 0)
            fill_price = None
            if filled_qty > 0:
                cum = float(raw.get("cummulativeQuoteQty") or 0)
                fill_price = cum / filled_qty if cum else None
            mapped = "filled" if status == "filled" else "submitted"
            return OrderResult(
                broker_order_id=str(raw.get("orderId")),
                status=mapped,
                filled_price=fill_price,
                filled_qty=filled_qty or None,
                submitted_at=now,
                filled_at=now if mapped == "filled" else None,
                raw=raw,
            )
        except httpx.HTTPStatusError as exc:
            body = exc.response.text[:300]
            logger.warning("Binance user order failed", error=body)
            return OrderResult(
                broker_order_id=None,
                status="rejected",
                filled_price=None,
                filled_qty=None,
                submitted_at=now,
                error=body,
                raw={},
            )
        except Exception as exc:  # noqa: BLE001
            return OrderResult(
                broker_order_id=None,
                status="error",
                filled_price=None,
                filled_qty=None,
                submitted_at=now,
                error=str(exc),
                raw={},
            )
