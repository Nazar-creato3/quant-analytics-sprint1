"""Portfolio factor sensitivities, Euler shares, ENB (prompt 65)."""
from __future__ import annotations

from time import perf_counter
from typing import Any, Mapping, Sequence

import numpy as np

from app.services.explanations.service import filter_wording
from app.services.factor_lens.betas import ridge_betas, shrink_to_industry, window_slice
from app.services.factor_lens.decompose import factor_variance_shares
from app.services.factor_lens.enb import enb_from_returns
from app.services.factor_lens.names import FACTOR_LABELS_RU, FACTOR_ORDER, LOW_R2
from app.services.factor_lens.orthogonalize import sequential_orthogonalize
from app.services.factor_lens.store import get_panel, snapshot
from app.services.qa.feature_flags import is_enabled
from app.services.risk_engine.series import get_series
from app.services.risk_engine.service import _holdings_from_book, _nav_weights


def _asset_matrix(tickers: Sequence[str]) -> tuple[np.ndarray, list[str]]:
    series = {t: get_series(t) for t in tickers}
    present = [t for t, s in series.items() if len(s) >= 20]
    if not present:
        return np.zeros((0, 0)), []
    length = min(len(series[t]) for t in present)
    matrix = np.column_stack([np.asarray(series[t][-length:], dtype=float) for t in present])
    return matrix, present


def _industry_means(
    per_asset: Mapping[str, dict[str, float]],
    industry_of: Mapping[str, str] | None,
) -> dict[str, dict[str, float]]:
    if not industry_of:
        return {}
    buckets: dict[str, list[dict[str, float]]] = {}
    for ticker, betas in per_asset.items():
        buckets.setdefault(industry_of.get(ticker, ""), []).append(betas)
    means: dict[str, dict[str, float]] = {}
    for industry, rows in buckets.items():
        if not industry:
            continue
        acc: dict[str, list[float]] = {}
        for row in rows:
            for name, value in row.items():
                if value == value:
                    acc.setdefault(name, []).append(value)
        means[industry] = {k: float(np.mean(v)) for k, v in acc.items()}
    return means


def explain_portfolio(
    user_id: str,
    *,
    mode: str = "paper",
    industry_of: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    started = perf_counter()
    if not is_enabled("qa_factor_lens"):
        return {"data_status": "нет данных", "reason": "нет данных"}
    raw = get_panel()
    if not raw:
        empty = snapshot()
        empty["elapsed_ms"] = round((perf_counter() - started) * 1000.0, 3)
        return empty
    ortho = sequential_orthogonalize(raw)
    holdings = _holdings_from_book(user_id, mode)
    weights = _nav_weights(holdings)
    tickers = [str(h["ticker"]).upper() for h in holdings]
    matrix, present = _asset_matrix(tickers)
    if weights is None or not present:
        payload = snapshot()
        payload["data_status"] = "нет данных"
        payload["reason"] = "нет весов или рядов бумаг"
        payload["elapsed_ms"] = round((perf_counter() - started) * 1000.0, 3)
        return payload
    weight_map = {t: w for t, w in zip(tickers, weights, strict=False)}
    aligned_w = np.asarray([weight_map.get(t, 0.0) for t in present], dtype=float)
    if aligned_w.sum() > 0:
        aligned_w = aligned_w / aligned_w.sum()
    per_asset: dict[str, dict[str, float]] = {}
    r2_assets: dict[str, float] = {}
    for i, ticker in enumerate(present):
        betas, r2 = ridge_betas(window_slice(matrix[:, i]), ortho, names=list(ortho))
        per_asset[ticker] = betas
        r2_assets[ticker] = r2
    industry_means = _industry_means(per_asset, industry_of)
    if industry_of and industry_means:
        for ticker in list(per_asset):
            mean = industry_means.get(industry_of.get(ticker, ""), None)
            per_asset[ticker] = shrink_to_industry(per_asset[ticker], mean)
    port_betas = {name: 0.0 for name in ortho}
    for ticker, betas in per_asset.items():
        w = float(aligned_w[present.index(ticker)])
        for name, value in betas.items():
            if value == value:
                port_betas[name] += w * value
    port_ret = list(matrix @ aligned_w)
    check_betas, port_r2 = ridge_betas(port_ret, ortho, names=list(ortho))
    shares = factor_variance_shares(port_betas, ortho, port_ret)
    enb = enb_from_returns(matrix, aligned_w)
    quality = "ok"
    note = None
    if port_r2 != port_r2:
        quality = "нет данных"
        note = "нет R² портфеля"
    elif port_r2 < LOW_R2:
        quality = "частично"
        note = "модель объясняет малую часть риска"
    top = sorted(
        ((n, shares.get(n)) for n in FACTOR_ORDER if shares.get(n) is not None),
        key=lambda kv: abs(float(kv[1] or 0.0)),
        reverse=True,
    )
    parts = [
        f"{int(round(abs(float(share)) * 100))}% риска — {FACTOR_LABELS_RU.get(name, name)}"
        for name, share in top[:3]
        if share is not None
    ]
    sentence = ", ".join(parts) + "." if parts else "нет данных"
    if parts and filter_wording(sentence):
        sentence = "нет данных"
    payload = snapshot()
    payload.update(
        {
            "portfolio_id": user_id,
            "mode": mode,
            "sensitivities": {t: per_asset[t] for t in present},
            "portfolio_betas": port_betas,
            "portfolio_betas_check": check_betas,
            "risk_shares": shares,
            "enb": enb["enb_pca"],
            "enb_min_torsion": enb["enb_min_torsion"],
            "diversification_ratio": enb["diversification_ratio"],
            "n_names": len(present),
            "r2_assets": r2_assets,
            "r2_portfolio": None if port_r2 != port_r2 else float(port_r2),
            "quality": quality,
            "quality_note": note,
            "sentence": sentence,
            "elapsed_ms": round((perf_counter() - started) * 1000.0, 3),
            "methodology": "/methodology/factor-lens",
        }
    )
    if payload.get("data_status") == "ok" and quality == "частично":
        payload["data_status"] = "частично"
        payload["reason"] = note
    return payload
