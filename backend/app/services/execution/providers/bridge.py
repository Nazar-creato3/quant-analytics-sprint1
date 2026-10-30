"""Bridge ExecutionProvider → legacy ExecutorProtocol (OrderRequest/OrderResult)."""
from __future__ import annotations

from datetime import datetime, timezone

from app.core.logging import get_logger
from app.services.execution.adapter import ExecutorProtocol, OrderRequest, OrderResult
from app.services.execution.providers.base import ExecutionProvider
from app.services.execution.providers.types import OrderType

logger = get_logger(__name__)


def _map_order_type(order_type: str) -> OrderType:
    ot = (order_type or "market").lower()
    if ot in ("limit", "stop_limit", "stop-limit"):
        return "limit"
    return "market"


class ExecutionProviderExecutor:
    """Wraps ExecutionProvider so existing order paths keep working."""

    def __init__(
        self,
        provider: ExecutionProvider,
        *,
        mode: str = "live",
        account_mode: str = "live",
    ) -> None:
        self._provider = provider
        self._mode = mode
        self._account_mode = account_mode

    async def submit_order(self, req: OrderRequest) -> OrderResult:
        from app.services.execution.adapter import _guard_broker_submission, requires_broker_paper_simulation
        from app.services.execution.providers.types import ProviderKind

        _guard_broker_submission(req)
        now = datetime.now(timezone.utc)
        provider_kind = getattr(self._provider, "kind", None)
        if provider_kind in (ProviderKind.BYBIT_TOKENIZED, ProviderKind.MEXC_TOKENIZED):
            if requires_broker_paper_simulation(self._account_mode):
                return OrderResult(
                    broker_order_id=None,
                    status="rejected",
                    filled_price=None,
                    filled_qty=None,
                    submitted_at=now,
                    error="Live trading not unlocked",
                    raw={
                        "execution_mode": "paper",
                        "provider": str(provider_kind),
                        "simulated_block": True,
                    },
                )
        order_type = _map_order_type(req.order_type)
        price = req.limit_price or req.stop_price

        result = await self._provider.place_order(
            req.ticker,
            req.side.lower(),  # type: ignore[arg-type]
            req.qty,
            order_type=order_type,
            price=price,
            client_order_id=req.client_order_id,
        )
        if not result.ok or not result.order:
            return OrderResult(
                broker_order_id=None,
                status="rejected",
                filled_price=None,
                filled_qty=None,
                submitted_at=now,
                error=result.error or "Order rejected",
                raw={"provider": getattr(self._provider, "kind", None)},
            )

        o = result.order
        status_map = {
            "filled": "filled",
            "partial": "submitted",
            "submitted": "submitted",
            "pending": "submitted",
            "cancelled": "rejected",
            "rejected": "rejected",
            "error": "error",
        }
        return OrderResult(
            broker_order_id=o.id,
            status=status_map.get(o.status, "submitted"),
            filled_price=o.filled_price,
            filled_qty=o.filled_qty if o.filled_qty else None,
            submitted_at=o.submitted_at,
            filled_at=o.filled_at,
            error=o.error,
            raw={**(o.raw or {}), "execution_mode": self._mode, "provider": str(getattr(self._provider, "kind", ""))},
        )


def wrap_provider(
    provider: ExecutionProvider,
    *,
    mode: str = "live",
    account_mode: str = "live",
) -> ExecutorProtocol:
    return ExecutionProviderExecutor(provider, mode=mode, account_mode=account_mode)
