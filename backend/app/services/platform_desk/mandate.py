"""Per-user IPS: cap, max risk, banned names, ESG keywords on free headlines."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

from app.core.config import settings


def _root() -> Path:
    raw = getattr(settings, "PLATFORM_IPS_DIR", "") or ""
    return Path(raw) if str(raw).strip() else Path("/app/data/platform/ips")


@dataclass(frozen=True, slots=True)
class IPS:
    user_id: str
    deploy_cap: float | None
    max_risk_pct: float
    banned_tickers: tuple[str, ...]
    esg_keywords: tuple[str, ...]
    max_name_frac: float
    updated_at: str

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["banned_tickers"] = list(self.banned_tickers)
        d["esg_keywords"] = list(self.esg_keywords)
        return d


def _path(user_id: str) -> Path:
    safe = "".join(ch if ch.isalnum() or ch in "._@+-" else "_" for ch in str(user_id).strip()) or "paper"
    return _root() / f"{safe}.json"


def default_ips(user_id: str = "paper") -> IPS:
    cap = float(getattr(settings, "DEFAULT_PORTFOLIO_SIZE", 0.0) or 0.0) or None
    return IPS(
        user_id=str(user_id),
        deploy_cap=cap,
        max_risk_pct=float(getattr(settings, "MAX_RISK_PER_TRADE_PCT", 2.0) or 2.0),
        banned_tickers=(),
        esg_keywords=(),
        max_name_frac=min(1.0, float(getattr(settings, "MAX_POSITION_PCT", 10.0) or 10.0) / 100.0),
        updated_at="",
    )


def load_ips(user_id: str = "paper") -> IPS:
    path = _path(user_id)
    base = default_ips(user_id)
    if not path.is_file():
        return base
    try:
        row = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return base
    banned = tuple(str(x).upper() for x in (row.get("banned_tickers") or []) if str(x).strip())
    keys = tuple(str(x).lower() for x in (row.get("esg_keywords") or []) if str(x).strip())
    cap_raw = row.get("deploy_cap")
    try:
        cap = float(cap_raw) if cap_raw not in (None, "") else base.deploy_cap
    except (TypeError, ValueError):
        cap = base.deploy_cap
    return IPS(
        user_id=str(user_id),
        deploy_cap=cap if cap and cap > 0 else None,
        max_risk_pct=float(row.get("max_risk_pct") or base.max_risk_pct),
        banned_tickers=banned,
        esg_keywords=keys,
        max_name_frac=float(row.get("max_name_frac") or base.max_name_frac),
        updated_at=str(row.get("updated_at") or ""),
    )


def save_ips(ips: IPS) -> IPS:
    path = _path(ips.user_id)
    stamped = IPS(
        user_id=ips.user_id,
        deploy_cap=ips.deploy_cap,
        max_risk_pct=ips.max_risk_pct,
        banned_tickers=tuple(x.upper() for x in ips.banned_tickers),
        esg_keywords=tuple(x.lower() for x in ips.esg_keywords),
        max_name_frac=ips.max_name_frac,
        updated_at=datetime.now(timezone.utc).isoformat(),
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(stamped.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)
    return stamped


def esg_hits(text: str, keywords: Sequence[str]) -> list[str]:
    blob = str(text or "").lower()
    if not blob or not keywords:
        return []
    return [k for k in keywords if k and k.lower() in blob]


def cached_headlines(ticker: str) -> str:
    """Free news already in memory. No network from allocate/construct."""
    sym = str(ticker or "").upper()
    if not sym:
        return ""
    try:
        from app.services.terminal_platform.market.feed_freshness import get_cached_news

        cached = get_cached_news()
    except Exception:
        return ""
    if cached is None or not getattr(cached, "rows", None):
        return ""
    parts: list[str] = []
    for row in list(cached.rows)[:80]:
        if isinstance(row, dict):
            title = str(row.get("title") or row.get("headline") or "")
            tickers = str(row.get("ticker") or row.get("symbol") or row.get("tickers") or "")
        else:
            title = str(getattr(row, "title", "") or getattr(row, "headline", "") or "")
            tickers = str(getattr(row, "ticker", "") or getattr(row, "symbol", "") or "")
        blob = f"{title} {tickers}".upper()
        if sym in blob:
            parts.append(title)
        if len(parts) >= 12:
            break
    return " ".join(parts)


def ticker_blocked(ticker: str, ips: IPS, *, headlines: str = "") -> str | None:
    sym = str(ticker or "").upper()
    if not sym or sym in {"—", "-"}:
        return None
    if sym in ips.banned_tickers:
        return f"ips_banned:{sym}"
    hits = esg_hits(f"{sym} {headlines}", ips.esg_keywords)
    if hits:
        return f"ips_esg:{','.join(hits)}"
    return None


def apply_mandate(maneuvers: list[Any], *, user_id: str = "paper", deploy_cap: float = 0.0) -> list[Any]:
    """Veto banned/ESG names. Tighten risk % — never raise the operator cap."""
    ips = load_ips(user_id)
    from app.services.risk.portfolio_sizing import _is_tradeable_slot, _mark_no_trade

    cap = max(0.0, float(deploy_cap or 0.0))
    if ips.deploy_cap and ips.deploy_cap > 0 and cap > 0:
        cap = min(cap, float(ips.deploy_cap))
    for m in maneuvers:
        if not _is_tradeable_slot(m):
            continue
        ticker = str(getattr(m, "ticker", "") or "")
        text = " ".join(
            [
                str(getattr(m, attr, "") or "")
                for attr in ("catalyst", "rationale", "note")
            ]
            + [cached_headlines(ticker)]
        )
        reason = ticker_blocked(ticker, ips, headlines=text)
        if reason:
            _mark_no_trade(m, f"Mandate {reason}", deploy_cap=cap or deploy_cap)
            continue
        # max_risk_pct is a loss budget, not a second name-cap. Ticket size stays
        # conviction-weighted; we do not flatten every idea onto 2% of cap.
    return maneuvers
