"""Ingest an official QuantConnect / LEAN data folder you dumped from your account.

This is not a scraper. Drop the tree from `lean data download` (or QC Data
Explorer export) into QUANTCONNECT_DATA_DIR. We read latest rows only — no
tick replay, skip files over 8 MiB.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

from app.core.config import settings

MAX_FILE_BYTES = 8 * 1024 * 1024
MAX_FILES = 80


def lean_data_root() -> Path | None:
    raw = str(getattr(settings, "QUANTCONNECT_DATA_DIR", "") or "").strip()
    if raw:
        path = Path(raw)
        return path if path.is_dir() else None
    here = Path(__file__).resolve().parents[3] / "data" / "qc_lean"
    return here if here.is_dir() else None


def _iter_csvs(root: Path, needles: tuple[str, ...]) -> list[Path]:
    found: list[Path] = []
    try:
        for path in root.rglob("*.csv"):
            if not path.is_file():
                continue
            try:
                if path.stat().st_size > MAX_FILE_BYTES:
                    continue
            except OSError:
                continue
            blob = str(path).lower().replace("\\", "/")
            if any(n in blob for n in needles):
                found.append(path)
            if len(found) >= MAX_FILES:
                break
    except OSError:
        return []
    return found


def _prefer_index(paths: list[Path]) -> list[Path]:
    def rank(p: Path) -> tuple[int, str]:
        name = p.stem.lower()
        if name in {"spy", "spx", "es", "qqq"}:
            return (0, name)
        return (1, name)

    return sorted(paths, key=rank)


def _parse_csv_rows(path: Path) -> list[dict[str, Any]]:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    lines = [ln.strip() for ln in text.splitlines() if ln.strip() and not ln.lstrip().startswith("#")]
    if not lines:
        return []
    head = lines[0]
    headerish = any(tok in head.lower() for tok in ("date", "time", "ticker", "sentiment", "transaction", "headline", "title"))
    rows: list[dict[str, Any]] = []
    if headerish:
        keys = [k.strip().lower().replace(" ", "_") for k in head.split(",")]
        for line in lines[1:]:
            parts = [p.strip() for p in line.split(",")]
            rows.append({keys[i]: parts[i] if i < len(parts) else "" for i in range(len(keys))})
        return rows
    for line in lines:
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 2:
            continue
        row: dict[str, Any] = {"date": parts[0], "col1": parts[1]}
        if len(parts) > 2:
            row["col2"] = parts[2]
        joined = ",".join(parts).lower()
        if "purchase" in joined or "sale" in joined or "sell" in joined:
            row["transaction"] = next((p for p in parts if p.lower() in {"purchase", "sale", "sell", "buy"}), parts[1])
        rows.append(row)
    return rows


def _last_brain(paths: Iterable[Path]) -> float | None:
    from app.services.quant_desk.licensed_alt import brain_row_sentiment
    vals: list[float] = []
    for path in _prefer_index(list(paths))[:MAX_FILES]:
        rows = _parse_csv_rows(path)
        if not rows:
            continue
        last = rows[-1]
        sent = brain_row_sentiment(last)
        if sent is None:
            for key in ("col1", "sentiment_7_days", "sentiments_7_days"):
                if last.get(key) not in (None, ""):
                    try:
                        sent = max(-1.0, min(1.0, float(last[key])))
                        break
                    except (TypeError, ValueError):
                        continue
        if sent is not None:
            vals.append(sent)
        if path.stem.lower() in {"spy", "spx"}:
            return sent
    if not vals:
        return None
    return round(sum(vals) / len(vals), 4)


def _quiver(paths: list[Path]) -> float | None:
    from app.services.quant_desk.licensed_alt import congress_net_tilt
    acc: list[dict[str, Any]] = []
    for path in paths[:MAX_FILES]:
        acc.extend(_parse_csv_rows(path)[-40:])
        if len(acc) >= 120:
            break
    return congress_net_tilt(acc)


def _benzinga(paths: list[Path]) -> float | None:
    from app.services.quant_desk.licensed_alt import benzinga_headline_tilt
    items: list[dict[str, Any]] = []
    for path in paths[:20]:
        for row in _parse_csv_rows(path)[-30:]:
            items.append(
                {
                    "title": row.get("title") or row.get("headline") or row.get("col1") or "",
                    "teaser": row.get("teaser") or row.get("summary") or "",
                    "sentiment": row.get("sentiment") or row.get("sentiment_score"),
                }
            )
    return benzinga_headline_tilt(items)


def _morningstar(paths: list[Path]) -> float | None:
    from app.services.quant_desk.licensed_alt import pe_to_growth_tilt
    for path in _prefer_index(paths)[:MAX_FILES]:
        rows = _parse_csv_rows(path)
        if not rows:
            continue
        last = rows[-1]
        for key in ("pe", "pe_ttm", "peratiottm", "trailingpe", "col1"):
            if last.get(key) not in (None, ""):
                try:
                    return pe_to_growth_tilt(float(last[key]))
                except (TypeError, ValueError):
                    continue
    return None


def _spectral(paths: list[Path]) -> float | None:
    from app.services.quant_desk.licensed_alt import spectral_ofi_tilt
    for path in _prefer_index(paths)[:MAX_FILES]:
        name = str(path).lower()
        if any(tok in name for tok in ("tick", "quote", "trade", "nbbo")) and "flow" not in name:
            continue
        rows = _parse_csv_rows(path)
        if not rows:
            continue
        last = rows[-1]
        mapped = {
            "ofi": last.get("ofi") or last.get("order_flow_imbalance") or last.get("col1"),
            "imbalance": last.get("imbalance") or last.get("trade_imbalance") or last.get("col2"),
        }
        tilt = spectral_ofi_tilt(mapped)
        if tilt is not None:
            return tilt
    return None


def ingest_qc_lean_snapshot() -> dict[str, Any]:
    """Latest Brain / Benzinga / Quiver / Morningstar / Spectral rows from the dump."""
    empty = {
        "brain_tilt": None,
        "benzinga_tilt": None,
        "quiver_tilt": None,
        "morningstar_tilt": None,
        "spectral_tilt": None,
        "qc_lean_root": None,
    }
    root = lean_data_root()
    if root is None:
        return empty
    empty["qc_lean_root"] = str(root)
    try:
        empty["brain_tilt"] = _last_brain(_iter_csvs(root, ("brain", "sentiment_usa", "bsi")))
    except Exception:
        pass
    try:
        empty["benzinga_tilt"] = _benzinga(_iter_csvs(root, ("benzinga",)))
    except Exception:
        pass
    try:
        empty["quiver_tilt"] = _quiver(_iter_csvs(root, ("quiver", "congresstrading", "congress-trading")))
    except Exception:
        pass
    try:
        empty["morningstar_tilt"] = _morningstar(_iter_csvs(root, ("morningstar",)))
    except Exception:
        pass
    try:
        empty["spectral_tilt"] = _spectral(_iter_csvs(root, ("spectral", "tick-flow", "tickflow")))
    except Exception:
        pass
    return empty
