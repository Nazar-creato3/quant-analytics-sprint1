"""MOEX ISS client — platform passport login only (MOEX has no public API keys).

Uses aiomoex (async ISSClient) when installed, with apimoex/requests fallback.
Never reads user trading-account vault keys.
"""
from __future__ import annotations

import asyncio
import ssl
import time
from typing import Any

import requests

from app.core.http_proxy import apply_direct_requests_session, httpx_ssl_verify
from app.core.logging import get_logger
from app.services.market_data.moex_spot import normalize_moex_symbol
from app.services.trading_keys.platform_keys import (
    moex_platform_configured,
    platform_env,
)

logger = get_logger(__name__)

MOEX_PASSPORT_URL = "https://passport.moex.com/authenticate"
MOEX_SHARE_ORDERBOOK_URL = (
    "https://iss.moex.com/iss/engines/stock/markets/shares/boards/{board}/securities/{ticker}/orderbook.json"
)
MOEX_CETS_ORDERBOOK_URL = (
    "https://iss.moex.com/iss/engines/currency/markets/selt/boards/CETS/securities/{ticker}/orderbook.json"
)
MOEX_SHARE_SECURITIES_URL = (
    "https://iss.moex.com/iss/engines/stock/markets/shares/securities/{ticker}.json"
)

_BOARD_PREFERENCE = ("TQBR", "TQTF", "SMAL", "TQOB", "TQCB")
_APMOEX_BASE_KEYS = frozenset({"iss.json", "iss.meta"})

_PASSPORT_COOKIE_CACHE: dict[str, Any] = {"cookies": {}, "expires_at": 0.0}
_PASSPORT_TTL_SEC = 1800


def moex_platform_orderbook_configured() -> bool:
    return moex_platform_configured()


def _ssl_context() -> ssl.SSLContext | bool:
    verify = httpx_ssl_verify()
    if verify is False:
        return False
    if verify is True:
        return True
    return ssl.create_default_context(cafile=str(verify))


def _iss_query_args(extra: dict[str, Any] | None = None) -> dict[str, Any]:
    args = dict(extra or {})
    for key in _APMOEX_BASE_KEYS:
        args.pop(key, None)
    return args


def _moex_passport_login(session: requests.Session, username: str, password: str) -> bool:
    try:
        resp = session.get(
            MOEX_PASSPORT_URL,
            auth=(username, password),
            timeout=20,
            allow_redirects=True,
        )
        if resp.status_code >= 400:
            logger.warning("MOEX passport authenticate failed", status=resp.status_code)
            return False
        if "MicexPassportCert" in session.cookies:
            return True
        session.auth = (username, password)
        return True
    except Exception as exc:
        logger.warning("MOEX passport authenticate error", error=str(exc))
        return False


def build_requests_session() -> requests.Session:
    """Sync requests session with MOEX ISS passport (email + password)."""
    session = requests.Session()
    apply_direct_requests_session(session)
    session.verify = httpx_ssl_verify()

    user = platform_env("MOEX_USERNAME")
    password = platform_env("MOEX_PASSWORD")
    token = platform_env("MOEX_API_TOKEN")
    if user and password:
        now = time.time()
        if _PASSPORT_COOKIE_CACHE["cookies"] and now < _PASSPORT_COOKIE_CACHE["expires_at"]:
            session.cookies.update(_PASSPORT_COOKIE_CACHE["cookies"])
        else:
            _moex_passport_login(session, user, password)
            _PASSPORT_COOKIE_CACHE["cookies"] = dict(session.cookies)
            _PASSPORT_COOKIE_CACHE["expires_at"] = now + _PASSPORT_TTL_SEC
    elif token:
        session.headers["Authorization"] = f"Bearer {token}"
    return session


def normalize_iss_tables(payload: Any) -> dict[str, Any] | None:
    """Normalize aiomoex list-of-dicts and raw ISS {columns,data} into one shape."""
    if not isinstance(payload, dict):
        return None
    out: dict[str, Any] = {}
    for key, block in payload.items():
        if isinstance(block, dict) and "data" in block:
            out[key] = block
            continue
        if isinstance(block, list):
            if not block:
                out[key] = {"columns": [], "data": []}
                continue
            if isinstance(block[0], dict):
                columns = list(block[0].keys())
                rows = [[row.get(col) for col in columns] for row in block]
                out[key] = {"columns": columns, "data": rows}
                continue
        out[key] = block
    return out


def _sync_fetch_json(url: str, params: dict[str, Any] | None = None) -> dict[str, Any] | None:
    session = build_requests_session()
    try:
        resp = session.get(url, params=params or {"iss.meta": "off"}, timeout=20)
        resp.raise_for_status()
    except Exception as exc:
        logger.warning("MOEX ISS fetch failed", url=url, error=str(exc))
        return None

    content_type = (resp.headers.get("content-type") or "").lower()
    if "html" in content_type or (resp.text or "").lstrip().startswith("<!"):
        logger.warning("MOEX ISS returned HTML (passport/subscription required)", url=url)
        return None

    try:
        payload = resp.json()
    except Exception:
        return None
    return normalize_iss_tables(payload) if isinstance(payload, dict) else None


async def _aiomoex_fetch_json(url: str, params: dict[str, Any] | None = None) -> dict[str, Any] | None:
    try:
        import aiohttp
        import aiomoex
    except ImportError:
        return None

    user = platform_env("MOEX_USERNAME")
    password = platform_env("MOEX_PASSWORD")
    token = platform_env("MOEX_API_TOKEN")
    headers: dict[str, str] = {}
    auth = aiohttp.BasicAuth(user, password) if user and password else None
    if token and not auth:
        headers["Authorization"] = f"Bearer {token}"

    timeout = aiohttp.ClientTimeout(total=20)
    ssl_ctx = _ssl_context()
    try:
        async with aiohttp.ClientSession(
            auth=auth,
            headers=headers,
            timeout=timeout,
            trust_env=False,
        ) as session:
            if user and password:
                try:
                    async with session.get(
                        MOEX_PASSPORT_URL,
                        ssl=ssl_ctx,
                        allow_redirects=True,
                    ) as resp:
                        await resp.read()
                except Exception as exc:
                    logger.warning("MOEX passport (aiomoex) failed", error=str(exc))
            iss = aiomoex.ISSClient(session, url, _iss_query_args(params))
            data = await iss.get()
    except Exception as exc:
        logger.warning("aiomoex ISS fetch failed", url=url, error=str(exc))
        return None
    return normalize_iss_tables(data)


async def fetch_moex_iss_json(url: str, params: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """Fetch ISS JSON via aiomoex + platform passport, then sync fallback."""
    payload = await _aiomoex_fetch_json(url, params)
    if payload:
        return payload
    return await asyncio.to_thread(_sync_fetch_json, url, params)


def _pick_board_from_marketdata(payload: dict[str, Any]) -> str | None:
    marketdata = payload.get("marketdata") or {}
    columns = marketdata.get("columns") or []
    rows = marketdata.get("data") or []
    if not columns or not rows:
        return None

    def _idx(name: str) -> int | None:
        try:
            return columns.index(name)
        except ValueError:
            return None

    board_idx = _idx("BOARDID")
    bid_idx = _idx("BID")
    offer_idx = _idx("OFFER")
    last_idx = _idx("LAST")
    if board_idx is None:
        return None

    active: list[str] = []
    for row in rows:
        if not row or len(row) <= board_idx:
            continue
        board = str(row[board_idx] or "").upper()
        if not board:
            continue
        has_quote = False
        for idx in (bid_idx, offer_idx, last_idx):
            if idx is None or len(row) <= idx:
                continue
            val = row[idx]
            try:
                if val is not None and float(val) > 0:
                    has_quote = True
                    break
            except (TypeError, ValueError):
                continue
        if has_quote:
            active.append(board)

    for preferred in _BOARD_PREFERENCE:
        if preferred in active:
            return preferred
    return active[0] if active else None


async def resolve_moex_share_board(ticker: str) -> str:
    """Resolve MOEX equity board for order book (TQBR, TQTF, …)."""
    bare = normalize_moex_symbol(ticker)
    url = MOEX_SHARE_SECURITIES_URL.format(ticker=bare)
    payload = await fetch_moex_iss_json(
        url,
        {"iss.only": "marketdata"},
    )
    board = _pick_board_from_marketdata(payload) if payload else None
    return board or "TQBR"


async def fetch_moex_share_orderbook_json(ticker: str, *, board: str | None = None) -> dict[str, Any] | None:
    bare = normalize_moex_symbol(ticker)
    resolved_board = board or await resolve_moex_share_board(bare)
    url = MOEX_SHARE_ORDERBOOK_URL.format(board=resolved_board, ticker=bare)
    payload = await fetch_moex_iss_json(url, {})
    rows = (payload or {}).get("orderbook", {}).get("data") if payload else None
    if rows:
        return payload

    if resolved_board != "TQBR":
        fallback_url = MOEX_SHARE_ORDERBOOK_URL.format(board="TQBR", ticker=bare)
        fallback = await fetch_moex_iss_json(fallback_url, {})
        if fallback and fallback.get("orderbook", {}).get("data"):
            return fallback
    return payload


async def fetch_moex_cets_orderbook_json(ticker: str) -> dict[str, Any] | None:
    url = MOEX_CETS_ORDERBOOK_URL.format(ticker=ticker.upper())
    return await fetch_moex_iss_json(url, {})
