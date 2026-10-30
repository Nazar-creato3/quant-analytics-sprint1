"""62: investor costs from book fees; fund TER and spread stay no-data without 61/58B."""
from __future__ import annotations

from datetime import date
from decimal import Decimal, ROUND_HALF_EVEN
from typing import Any

from app.services.legal.catalog import load_ui_texts
from app.services.portfolio_book.store import get_book
from app.services.qa.feature_flags import is_enabled
from app.services.returns.service import compute_returns

KOPECK = Decimal("0.01")
PP = Decimal("0.0001")


def analyze_costs(*, user_id: str, mode: str, year: int | None = None) -> dict[str, Any]:
    if not is_enabled("qa_62_costs"):
        raise RuntimeError("qa_62_costs off")
    texts = load_ui_texts().get("d62") or {}
    txns = get_book().transactions(user_id=user_id, mode=mode)
    if year is not None:
        txns = [t for t in txns if t.event_time.year == year]
    broker = sum((abs(t.amount) for t in txns if t.kind == "fee"), Decimal("0"))
    taxes = sum((abs(t.amount) for t in txns if t.kind == "tax"), Decimal("0"))
    ret = compute_returns(user_id=user_id, mode=mode, period="inception")
    avg = ret.end_value
    pct = None
    if isinstance(avg, Decimal) and avg > 0:
        pct = (broker / avg).quantize(PP, rounding=ROUND_HALF_EVEN)
    ten = _ten_year(avg, pct, user_id=user_id, mode=mode)
    lines = [
        {"id": "broker", "rubles": str(broker.quantize(KOPECK)), "source": "book.fee", "data_status": "ok"},
        {"id": "fund_ter", "rubles": None, "source": "61 fund_meta.ter", "data_status": "нет данных", "reason": "модуль 61 не дал TER"},
        {"id": "spread", "rubles": None, "source": "58B", "data_status": "нет данных"},
        {"id": "tax", "rubles": str(taxes.quantize(KOPECK)), "source": "book.tax", "data_status": "ok", "in_total": False},
    ]
    missing = [row["id"] for row in lines if row.get("data_status") != "ok" and row.get("in_total") is not False]
    status = "нет данных"
    if txns:
        status = "частично" if missing else "ok"
    return {
        "data_status": status,
        "reason": None if status == "ok" else ("частично: " + ", ".join(missing) if missing else "нет операций"),
        "year": year,
        "total_rubles": str(broker.quantize(KOPECK)),
        "total_pct": str(pct) if pct is not None else None,
        "lines": lines,
        "ten_year": ten,
        "tariffs": {"data_status": "нет данных", "reason": "нет справочника тарифа в этом расчёте"},
        "k1": ten.get("k1"),
        "texts": texts,
        "methodology": "/methodology/costs",
        "as_of": date.today().isoformat(),
    }


def _ten_year(avg: Decimal | None, cost_pct: Decimal | None, *, user_id: str, mode: str) -> dict[str, Any]:
    if avg is None or cost_pct is None:
        return {"data_status": "нет данных", "reason": "нет средней стоимости", "delta": None}
    k1_payload: dict[str, Any] = {}
    k1_rate = None
    if is_enabled("qa_k1_benchmark"):
        from app.services.benchmark_alt.service import as_dict, compare_simple_alternatives

        try:
            k1_payload = as_dict(compare_simple_alternatives(user_id=user_id, mode=mode, period="inception"))
            for row in k1_payload.get("alternatives") or []:
                if row.get("ticker") == "RGBITR" and row.get("twr") is not None:
                    k1_rate = Decimal(str(row["twr"]))
                    break
        except Exception:
            k1_payload = {"status": "нет данных"}
    if k1_rate is None:
        return {"data_status": "нет данных", "reason": "нет данных", "delta": None, "k1": k1_payload}
    with_c = avg * ((Decimal("1") + k1_rate - cost_pct) ** 10)
    without = avg * ((Decimal("1") + k1_rate) ** 10)
    delta = (without - with_c).quantize(KOPECK, rounding=ROUND_HALF_EVEN)
    return {
        "data_status": "ok",
        "reason": None,
        "note": "расчёт при неизменных условиях",
        "delta": str(delta),
        "k1_rate": str(k1_rate),
        "k1": k1_payload,
    }
