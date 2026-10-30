"""One optimizer: MV / risk-parity / inv-vol / conviction, then hard constraints.

Weights are fractions of *deploy cap*. Sum may be < 1: leftover is cash.
Never water-fill leftover into weak names (that was the $800-on-$250 class of bug).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Mapping, Sequence

import numpy as np

from app.services.construction.risk_model import blend_cov, tracking_error
from app.services.quant_desk.convex_alloc import inverse_vol_weights

Mode = Literal["mean_variance", "risk_parity", "inv_vol", "conviction"]


@dataclass(frozen=True, slots=True)
class Constraints:
    name_cap: float = 0.10
    sector_cap: float = 0.30
    turnover_cap: float = 0.40  # one-way
    participation: float = 0.10  # of ADV
    exposure_cap: float = 0.80
    cash_buffer: float = 0.20
    long_only: bool = True
    te_cap: float = 0.0
    beta_abs_cap: float = 2.0
    country_cap: float = 1.0
    risk_aversion: float = 4.0
    te_aversion: float = 8.0
    cvar_aversion: float = 2.0
    impact_aversion: float = 1.0
    restricted: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class NameSpec:
    symbol: str
    mu: float
    vol: float
    sector: str = "UNK"
    adv_usd: float = 0.0
    current_w: float = 0.0
    conviction: float = 0.0
    beta: float = 1.0
    country: str = "US"
    restricted: bool = False
    size: float = 0.0


@dataclass(frozen=True, slots=True)
class OptimizedBook:
    weights: tuple[float, ...]
    cash: float
    mode: str
    notes: tuple[str, ...] = field(default_factory=tuple)
    turnover: float = 0.0
    te: float = 0.0
    port_beta: float = 0.0
    cvar: float = 0.0


def _cov(hist: Mapping[str, Sequence[float]] | None, specs: Sequence[NameSpec]):
    book = blend_cov(
        [s.symbol for s in specs],
        [s.vol for s in specs],
        hist=hist,
        sectors=[s.sector for s in specs],
        size=[s.size for s in specs],
    )
    return book


def _raw(mode: Mode, specs: Sequence[NameSpec], cov: np.ndarray) -> np.ndarray:
    n = len(specs)
    if n == 0:
        return np.asarray([])
    if mode == "inv_vol":
        w = inverse_vol_weights([s.vol for s in specs])
        return np.asarray(w, dtype=float)
    if mode == "conviction":
        c = np.array([max(0.0, s.conviction) for s in specs], dtype=float)
        peak = float(c.max()) if c.size else 0.0
        if peak <= 0:
            return np.zeros(n)
        # Unitless rank in [0, 1]. Name cap is applied later; do not 1/n-normalize
        # (that would push every similar score onto the 10% ceiling).
        return c / peak
    if mode == "risk_parity":
        vol = np.sqrt(np.clip(np.diag(cov), 1e-8, None))
        w = 1.0 / vol
        w = w / w.sum()
        for _ in range(24):
            mcr = cov @ w
            rc = w * mcr
            target = float(rc.sum()) / n
            adj = target / np.clip(rc, 1e-12, None)
            w = np.clip(w * np.sqrt(adj), 1e-8, None)
            w = w / w.sum()
        return w
    # mean-variance: Σ^{-1} μ, long-only clip
    mu = np.array([s.mu for s in specs], dtype=float)
    try:
        inv = np.linalg.pinv(cov)
        raw = inv @ mu
    except np.linalg.LinAlgError:
        raw = mu
    raw = np.maximum(raw, 0.0)
    if float(raw.sum()) <= 0:
        return np.ones(n) / n
    return raw / raw.sum()


def _clip_name_sector_cash(
    w: np.ndarray,
    specs: Sequence[NameSpec],
    cons: Constraints,
    notes: list[str],
) -> np.ndarray:
    if cons.long_only:
        w = np.maximum(w, 0.0)
    expo0 = min(cons.exposure_cap, 1.0 - cons.cash_buffer)
    tot0 = float(sum(abs(x) for x in w))
    if tot0 > expo0 + 1e-12:
        w = w * (expo0 / tot0)
    blocked = {str(x).upper() for x in cons.restricted}
    for i, s in enumerate(specs):
        if s.restricted or s.symbol.upper() in blocked:
            w[i] = 0.0
            if "restricted" not in notes:
                notes.append("restricted")
    w = np.minimum(w, cons.name_cap)
    by_cty: dict[str, list[int]] = {}
    for i, s in enumerate(specs):
        by_cty.setdefault((s.country or "US").upper(), []).append(i)
    for cty, idxs in by_cty.items():
        gross = float(sum(abs(w[i]) for i in idxs))
        if gross > cons.country_cap + 1e-12:
            scale = cons.country_cap / gross
            for i in idxs:
                w[i] *= scale
            tag = f"country_cap:{cty}"
            if tag not in notes:
                notes.append(tag)
    port_beta = float(sum(w[i] * specs[i].beta for i in range(len(specs))))
    if abs(port_beta) > cons.beta_abs_cap + 1e-12 and abs(port_beta) > 1e-12:
        w = w * (cons.beta_abs_cap / abs(port_beta))
        if "beta_cap" not in notes:
            notes.append("beta_cap")
    by_sec: dict[str, list[int]] = {}
    for i, s in enumerate(specs):
        by_sec.setdefault(s.sector or "UNK", []).append(i)
    for sec, idxs in by_sec.items():
        gross = float(sum(abs(w[i]) for i in idxs))
        if gross > cons.sector_cap + 1e-12:
            scale = cons.sector_cap / gross
            for i in idxs:
                w[i] *= scale
            tag = f"sector_cap:{sec}"
            if tag not in notes:
                notes.append(tag)
    expo = min(cons.exposure_cap, 1.0 - cons.cash_buffer)
    tot = float(sum(abs(x) for x in w))
    if tot > expo + 1e-12:
        w = w * (expo / tot)
        if "cash_buffer" not in notes:
            notes.append("cash_buffer")
    return w


def _apply_constraints(
    w: np.ndarray,
    specs: Sequence[NameSpec],
    *,
    cons: Constraints,
    deploy_cap: float = 0.0,
) -> tuple[np.ndarray, list[str], float]:
    notes: list[str] = []
    n = len(specs)
    if n == 0:
        return w, notes, 0.0
    w = _clip_name_sector_cash(w, specs, cons, notes)
    if deploy_cap > 0:
        for i, s in enumerate(specs):
            if s.adv_usd > 0 and cons.participation > 0:
                max_w = (s.adv_usd * cons.participation) / deploy_cap
                if w[i] > max_w + 1e-12:
                    w[i] = max(0.0, max_w)
                    notes.append(f"adv:{s.symbol}")
        w = _clip_name_sector_cash(w, specs, cons, notes)
    prev = np.array([s.current_w for s in specs], dtype=float)
    one_way = 0.5 * float(np.abs(w - prev).sum())
    if one_way > cons.turnover_cap + 1e-12 and cons.turnover_cap >= 0 and one_way > 1e-12:
        alpha = cons.turnover_cap / one_way
        w = prev + alpha * (w - prev)
        notes.append("turnover")
        one_way = cons.turnover_cap
        w = _clip_name_sector_cash(w, specs, cons, notes)
        one_way = 0.5 * float(np.abs(w - prev).sum())
    return w, notes, one_way


def optimize(
    specs: Sequence[NameSpec],
    *,
    mode: Mode = "conviction",
    hist: Mapping[str, Sequence[float]] | None = None,
    cons: Constraints | None = None,
    deploy_cap: float = 0.0,
    bench_weights: Sequence[float] | None = None,
) -> OptimizedBook:
    c = cons or Constraints()
    n = len(specs)
    if n == 0:
        return OptimizedBook((), 1.0, mode, ("empty",), 0.0)
    rb = _cov(hist, specs)
    cov = rb.cov
    notes_risk = list(rb.notes)
    if mode == "mean_variance":
        from app.services.construction.qp import qp_step
        from app.services.construction.risk_model import _panel

        panel = _panel(hist, [s.symbol for s in specs])
        bench = (
            np.asarray(list(bench_weights)[:n], dtype=float)
            if bench_weights is not None
            else np.zeros(n)
        )
        if bench.size < n:
            bench = np.zeros(n)
        w = qp_step(
            np.array([s.mu for s in specs], dtype=float),
            cov,
            w0=np.array([s.current_w for s in specs], dtype=float),
            bench=bench,
            adv=np.array([s.adv_usd for s in specs], dtype=float),
            deploy_cap=deploy_cap,
            risk_aversion=c.risk_aversion,
            te_aversion=c.te_aversion,
            cvar_aversion=c.cvar_aversion,
            impact_aversion=c.impact_aversion,
            hist_panel=panel,
        )
    else:
        w = _raw(mode, specs, cov)
        if mode == "conviction":
            # Peak idea sits at name cap; weaker names scale down. Leftover is cash.
            w = w * float(c.name_cap)
        bench = (
            np.asarray(list(bench_weights)[:n], dtype=float)
            if bench_weights is not None and len(bench_weights) >= n
            else np.zeros(n)
        )
    w, notes, to = _apply_constraints(w, specs, cons=c, deploy_cap=deploy_cap)
    notes = notes_risk + notes
    te = tracking_error(w, bench, cov)
    if c.te_cap > 0 and te > c.te_cap + 1e-12:
        active = w - bench
        # shrink active risk; leftover becomes cash
        scale = c.te_cap / te
        w = bench + active * scale
        w = np.maximum(w, 0.0) if c.long_only else w
        notes.append("te_cap")
        te = tracking_error(w, bench, cov)
        w, extra, to = _apply_constraints(w, specs, cons=c, deploy_cap=deploy_cap)
        notes.extend(extra)
    cash = max(0.0, 1.0 - float(sum(abs(x) for x in w)))
    port_beta = float(sum(float(w[i]) * specs[i].beta for i in range(n)))
    from app.services.construction.risk_model import gaussian_cvar

    port_vol = float(np.sqrt(max(float(w @ cov @ w), 0.0))) if n else 0.0
    return OptimizedBook(
        weights=tuple(round(float(x), 8) for x in w),
        cash=round(cash, 8),
        mode=mode,
        notes=tuple(dict.fromkeys(notes)),
        turnover=round(to, 8),
        te=round(te, 8),
        port_beta=round(port_beta, 6),
        cvar=round(gaussian_cvar(port_vol), 8),
    )
