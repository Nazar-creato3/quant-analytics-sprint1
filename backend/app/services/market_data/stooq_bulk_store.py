"""Stooq daily bulk store — overwrite-only nightly/local ingest → OHLCV source.

Layout under STOOQ_BULK_DIR (default ``backend/data/stooq``)::

    inbox/          drop ZIPs / CSVs here (cleared after successful sync)
    current/        live extract (fully replaced each sync)
    manifest.json   symbol → relative path + sync metadata
    downloads/      last HTTP fetch (replaced, then deleted after extract)

Disk policy: one live tree only — no day-by-day ZIP archive.
"""
from __future__ import annotations

import json
import re
import shutil
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from app.core.config import settings
from app.core.http_proxy import httpx_client_kwargs
from app.core.logging import get_logger
from app.services.market_data.stooq_client import stooq_symbol

logger = get_logger(__name__)

DEFAULT_PACKAGES: tuple[str, ...] = ("d_us_txt.zip", "d_world_txt.zip")
STOOQ_STATIC_BASE = "https://static.stooq.com/db/h/"

_BROWSER_HEADERS = {
    "Accept": "application/zip,application/octet-stream,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/152.0.0.0 Safari/537.36"
    ),
    "Referer": "https://stooq.com/db/h/",
}

# Polish Stooq CSV headers → English
_PL_HEADER = {
    "data": "date",
    "otwarcie": "open",
    "najwyzszy": "high",
    "najwyższy": "high",
    "najnizszy": "low",
    "najniższy": "low",
    "zamkniecie": "close",
    "zamknięcie": "close",
    "wolumen": "volume",
}


def _score_stooq_root(path: Path) -> int:
    score = 0
    try:
        if (path / "manifest.json").is_file():
            score += 2
        current = path / "current"
        if current.is_dir():
            # Cheap probe: any entry under current/ (avoid full rglob on huge trees).
            try:
                next(current.iterdir())
                score += 5
            except StopIteration:
                pass
        inbox = path / "inbox"
        if inbox.is_dir() and any(inbox.glob("*.zip")):
            score += 1
    except OSError:
        return 0
    return score


def _candidate_stooq_roots() -> list[Path]:
    cands: list[Path] = []
    raw = (settings.STOOQ_BULK_DIR or "").strip()
    if raw:
        cands.append(Path(raw))
    for p in (
        Path("/app/data/stooq"),
        Path("/app/backend/data/stooq"),
        Path("backend/data/stooq"),
        Path("data/stooq"),
    ):
        cands.append(p)
    try:
        cands.append(Path(settings.EUROSTAT_STORE_DIR).resolve().parent / "stooq")
    except Exception as exc:
        logger.debug("eurostat-derived stooq root skipped", error=str(exc)[:120])
    seen: set[str] = set()
    out: list[Path] = []
    for p in cands:
        key = str(p)
        if key in seen:
            continue
        seen.add(key)
        out.append(p)
    return out


def bulk_root() -> Path:
    """Prefer configured STOOQ_BULK_DIR; if empty mount, auto-pick root with data."""
    scored = [(_score_stooq_root(p), p) for p in _candidate_stooq_roots()]
    scored.sort(key=lambda x: (-x[0], str(x[1])))
    best_score, best = scored[0]
    configured = (settings.STOOQ_BULK_DIR or "").strip()
    if best_score == 0:
        logger.warning(
            "stooq_bulk_empty_mount",
            configured=configured or None,
            tried=[str(p) for _, p in scored[:6]],
            using=str(best),
            hint="Mount ./backend/data/stooq or drop d_us_txt.zip into inbox/",
        )
    elif configured and Path(configured) != best and best_score >= 5:
        logger.warning(
            "stooq_bulk_root_fallback",
            configured=configured,
            using=str(best),
            score=best_score,
        )
    return best


def packages_list() -> list[str]:
    raw = (settings.STOOQ_BULK_PACKAGES or "").strip()
    if not raw:
        return list(DEFAULT_PACKAGES)
    return [p.strip() for p in raw.split(",") if p.strip()]


def _manifest_path(root: Path | None = None) -> Path:
    return (root or bulk_root()) / "manifest.json"


def _current_dir(root: Path | None = None) -> Path:
    return (root or bulk_root()) / "current"


def ensure_layout(root: Path | None = None) -> Path:
    base = root or bulk_root()
    for name in ("inbox", "current", "downloads", "tmp"):
        (base / name).mkdir(parents=True, exist_ok=True)
    return base


def load_manifest(root: Path | None = None) -> dict[str, Any]:
    path = _manifest_path(root)
    if not path.is_file():
        return {"symbols": {}, "synced_at": None, "packages": []}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("stooq_manifest_read_failed", error=str(exc)[:160])
        return {"symbols": {}, "synced_at": None, "packages": []}


def save_manifest(payload: dict[str, Any], root: Path | None = None) -> None:
    base = ensure_layout(root)
    path = _manifest_path(base)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def build_symbol_index(extract_root: Path) -> dict[str, str]:
    """Map ``spy.us`` / ``btc.v`` → relative path under extract_root."""
    index: dict[str, str] = {}
    for path in extract_root.rglob("*.txt"):
        if not path.is_file():
            continue
        stem = path.stem.lower()
        if not stem or stem.startswith("."):
            continue
        try:
            rel = str(path.relative_to(extract_root)).replace("\\", "/")
        except ValueError:
            continue
        index[stem] = rel
        # Also index without leading ^ for indices (^dax → dax)
        if stem.startswith("^"):
            index[stem.lstrip("^")] = rel
    return index


def _alias_candidates(ticker: str) -> list[str]:
    """Resolve platform tickers to Stooq file stems."""
    raw = ticker.strip()
    primary = stooq_symbol(raw)
    out = [primary]
    upper = raw.upper().replace("-", "")
    if upper in {"BTCUSD", "BTCUSDT", "BTC"} or raw.upper() in {"BTC-USD", "BTCUSDT"}:
        out.extend(["btc.v", "btc.usd", "btcusd"])
    if raw.upper() in {"ETH-USD", "ETHUSDT", "ETH"}:
        out.extend(["eth.v", "eth.usd"])
    # bare symbol without .us
    if primary.endswith(".us"):
        out.append(primary[: -len(".us")])
    # dedupe preserve order
    seen: set[str] = set()
    uniq: list[str] = []
    for s in out:
        key = s.lower()
        if key not in seen:
            seen.add(key)
            uniq.append(key)
    return uniq


def resolve_symbol_file(ticker: str, root: Path | None = None) -> Path | None:
    base = root or bulk_root()
    manifest = load_manifest(base)
    symbols = manifest.get("symbols") or {}
    current = _current_dir(base)
    for stem in _alias_candidates(ticker):
        rel = symbols.get(stem)
        if rel:
            candidate = current / rel
            if candidate.is_file():
                return candidate
    if not current.is_dir():
        return None
    for stem in _alias_candidates(ticker):
        matches = list(current.rglob(f"{stem}.txt"))
        if matches:
            return matches[0]
    return None


def _normalize_header_cell(cell: str) -> str:
    key = cell.strip().lower()
    return _PL_HEADER.get(key, key)


def _parse_txt_bars(
    path: Path,
    *,
    start: datetime | None = None,
    end: datetime | None = None,
) -> list[dict[str, Any]]:
    text = path.read_text(encoding="utf-8", errors="replace").strip()
    lines = text.splitlines()
    if len(lines) < 2:
        return []
    header_cells = [_normalize_header_cell(c) for c in lines[0].split(",")]
    header = ",".join(header_cells)
    out: list[dict[str, Any]] = []
    start_d = start.date() if start else None
    end_d = end.date() if end else None

    def _emit(day: datetime, o: float, h: float, low: float, c: float, vol: float) -> None:
        d = day.date()
        if start_d and d < start_d:
            return
        if end_d and d > end_d:
            return
        ts = datetime(day.year, day.month, day.day, tzinfo=timezone.utc)
        out.append(
            {
                "timestamp": ts.isoformat(),
                "open": o,
                "high": h,
                "low": low,
                "close": c,
                "volume": vol,
                "source": "stooq_local",
            }
        )

    for line in lines[1:]:
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 5:
            continue
        try:
            if "date" in header and parts[0][:4].isdigit():
                day = datetime.strptime(parts[0][:10], "%Y-%m-%d")
                o, h, low, c = map(float, parts[1:5])
                vol = float(parts[5]) if len(parts) > 5 and parts[5] not in {"", "0"} else 0.0
                _emit(day, o, h, low, c, vol)
            elif len(parts) >= 7 and parts[2].isdigit() and len(parts[2]) == 8:
                day = datetime.strptime(parts[2], "%Y%m%d")
                o, h, low, c = map(float, parts[4:8] if len(parts) >= 8 else parts[3:7])
                vol = float(parts[8]) if len(parts) > 8 else 0.0
                _emit(day, o, h, low, c, vol)
        except (ValueError, TypeError, IndexError):
            continue
    return out


def read_bars(
    ticker: str,
    *,
    start: datetime | None = None,
    end: datetime | None = None,
    root: Path | None = None,
) -> list[dict[str, Any]]:
    path = resolve_symbol_file(ticker, root=root)
    if not path:
        return []
    try:
        return _parse_txt_bars(path, start=start, end=end)
    except Exception as exc:
        logger.debug("stooq_local_parse_failed", ticker=ticker, error=str(exc)[:160])
        return []


def read_latest_quote(ticker: str, *, root: Path | None = None) -> dict[str, Any]:
    bars = read_bars(ticker, root=root)
    if not bars:
        return {"ticker": ticker.upper(), "price": None, "source": "stooq_local"}
    last = bars[-1]
    prev = bars[-2]["close"] if len(bars) > 1 else last["close"]
    close = float(last["close"])
    change = ((close - float(prev)) / float(prev) * 100.0) if prev else None
    return {
        "ticker": ticker.upper(),
        "price": close,
        "change_pct": change,
        "volume": last.get("volume"),
        "source": "stooq_local",
    }


class StooqLocalClient:
    """File-backed Stooq daily bars/quotes from the overwrite bulk extract."""

    async def get_bars(
        self, ticker: str, timeframe: str, start: datetime, end: datetime
    ) -> list[dict[str, Any]]:
        if timeframe not in {"1d", "1w", "1wk"}:
            return []
        return read_bars(ticker, start=start, end=end)

    async def get_latest_quote(self, ticker: str) -> dict[str, Any]:
        return read_latest_quote(ticker)


def _download_headers() -> dict[str, str]:
    headers = dict(_BROWSER_HEADERS)
    cookie = (settings.STOOQ_COOKIE or "").strip()
    if cookie:
        headers["Cookie"] = cookie
    return headers


async def download_package(name: str, dest: Path) -> dict[str, Any]:
    """Download one regional ZIP into ``dest`` (overwrites previous file)."""
    url = f"{STOOQ_STATIC_BASE}{name}"
    key = (settings.STOOQ_API_KEY or "").strip()
    params = {"apikey": key} if key else None
    kwargs = httpx_client_kwargs(foreign=True, timeout=httpx.Timeout(300.0, connect=20.0))
    try:
        async with httpx.AsyncClient(**kwargs, headers=_download_headers(), follow_redirects=True) as client:
            resp = await client.get(url, params=params)
            text_head = (resp.text or "")[:240] if resp.headers.get("content-type", "").startswith("text") else ""
            body_preview = resp.content[:240]
            preview = text_head or body_preview.decode("utf-8", errors="replace")
            if "Exceeded the daily bandwidth limit" in preview or "daily hits limit" in preview.lower():
                return {
                    "package": name,
                    "ok": False,
                    "status": resp.status_code,
                    "error": "bandwidth_limit",
                    "hint": "Stooq daily quota hit — keep last current/ extract; retry tomorrow or use inbox ZIP.",
                }
            if resp.status_code in {401, 403, 404}:
                return {
                    "package": name,
                    "ok": False,
                    "status": resp.status_code,
                    "error": "auth_or_missing",
                    "hint": "Set STOOQ_COOKIE or drop ZIP into STOOQ_BULK_DIR/inbox/",
                }
            resp.raise_for_status()
            body = resp.content
            if len(body) < 1000 or body[:2] != b"PK":
                snippet = body[:80].decode("utf-8", errors="replace")
                return {
                    "package": name,
                    "ok": False,
                    "status": resp.status_code,
                    "error": "not_a_zip",
                    "hint": snippet,
                }
            dest.parent.mkdir(parents=True, exist_ok=True)
            if dest.exists():
                dest.unlink()
            dest.write_bytes(body)
            return {"package": name, "ok": True, "bytes": len(body), "path": str(dest)}
    except Exception as exc:
        return {"package": name, "ok": False, "error": str(exc)[:200]}


def _collect_inbox_zips(root: Path) -> list[Path]:
    inbox = root / "inbox"
    if not inbox.is_dir():
        return []
    zips = list(inbox.glob("d_*_txt.zip")) + list(inbox.glob("*.zip"))
    # Prefer canonical names; de-dupe by resolved path
    seen: set[Path] = set()
    out: list[Path] = []
    for path in sorted(zips, key=lambda p: p.name.lower()):
        key = path.resolve()
        if key in seen:
            continue
        seen.add(key)
        out.append(path)
    return out


def _collect_inbox_csvs(root: Path) -> list[Path]:
    inbox = root / "inbox"
    if not inbox.is_dir():
        return []
    return sorted(list(inbox.glob("*.csv")) + list(inbox.glob("*.CSV")))


def _safe_stem(name: str) -> str:
    stem = Path(name).stem.lower()
    stem = re.sub(r"\s*\(\d+\)$", "", stem)  # "d_world_txt (1)" → "d_world_txt"
    stem = re.sub(r"[^a-z0-9._^-]+", "_", stem).strip("._")
    return stem or "series"


def csv_to_stooq_txt(src: Path, dest: Path) -> int:
    """Normalize Stooq/Polish CSV → Date,Open,High,Low,Close,Volume txt. Returns bar count."""
    text = src.read_text(encoding="utf-8", errors="replace").strip()
    lines = text.splitlines()
    if len(lines) < 2:
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text("Date,Open,High,Low,Close,Volume\n", encoding="utf-8")
        return 0
    header = [_normalize_header_cell(c) for c in lines[0].split(",")]
    # Already English OHLCV
    out_lines = ["Date,Open,High,Low,Close,Volume"]
    count = 0
    for line in lines[1:]:
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 5:
            continue
        try:
            if parts[0][:4].isdigit() and "-" in parts[0]:
                day = parts[0][:10]
                o, h, low, c = parts[1:5]
                vol = parts[5] if len(parts) > 5 else "0"
            else:
                continue
            float(o)
            float(h)
            float(low)
            float(c)
            out_lines.append(f"{day},{o},{h},{low},{c},{vol}")
            count += 1
        except ValueError:
            continue
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text("\n".join(out_lines) + "\n", encoding="utf-8")
    _ = header  # normalized for future column-order maps
    return count


def _purge_dir_contents(path: Path) -> None:
    if not path.is_dir():
        return
    for child in path.iterdir():
        try:
            if child.is_dir():
                shutil.rmtree(child, ignore_errors=True)
            else:
                child.unlink(missing_ok=True)
        except Exception:
            continue


def cleanup_after_sync(root: Path, used_files: list[Path]) -> None:
    """Delete consumed inbox/downloads artifacts — keep only current + manifest."""
    base = ensure_layout(root)
    for path in used_files:
        try:
            if path.is_file() and path.resolve().is_relative_to((base / "inbox").resolve()):
                path.unlink(missing_ok=True)
            elif path.is_file() and path.resolve().is_relative_to((base / "downloads").resolve()):
                path.unlink(missing_ok=True)
        except Exception as exc:
            # Python <3.9 may lack is_relative_to — fallback
            logger.debug("stooq cleanup relative_to failed", error=str(exc)[:120])
            try:
                if path.is_file() and (str(path).startswith(str(base / "inbox")) or str(path).startswith(str(base / "downloads"))):
                    path.unlink(missing_ok=True)
            except Exception as exc2:
                logger.warning("stooq cleanup unlink failed", path=str(path), error=str(exc2)[:120])
    _purge_dir_contents(base / "downloads")
    # Remove leftover tmp / bak
    bak = base / "current.bak"
    if bak.exists():
        shutil.rmtree(bak, ignore_errors=True)
    _purge_dir_contents(base / "tmp")


# Windows device stems (PRN.us.txt → PRN) break zipfile.extractall.
_WIN_RESERVED_STEMS = {
    "con",
    "prn",
    "aux",
    "nul",
    *(f"com{i}" for i in range(1, 10)),
    *(f"lpt{i}" for i in range(1, 10)),
}


def _zip_member_is_win_reserved(member: str) -> bool:
    name = Path(member.replace("\\", "/")).name
    if not name or name.endswith("/"):
        return False
    stem = name.split(".", 1)[0].lower()
    return stem in _WIN_RESERVED_STEMS


def _safe_extract_zip(zpath: Path, staging: Path) -> int:
    """Extract ZIP skipping Windows-reserved basenames (e.g. prn.us.txt)."""
    written = 0
    skipped = 0
    with zipfile.ZipFile(zpath, "r") as zf:
        for info in zf.infolist():
            name = info.filename
            if not name or name.endswith("/") or info.is_dir():
                continue
            if _zip_member_is_win_reserved(name):
                skipped += 1
                continue
            target = staging / name
            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(info) as src, open(target, "wb") as dst:
                    shutil.copyfileobj(src, dst)
                written += 1
            except OSError as exc:
                logger.debug(
                    "stooq_zip_member_skip",
                    member=name[:120],
                    error=str(exc)[:120],
                )
                skipped += 1
    if skipped:
        logger.info("stooq_zip_skipped_reserved", path=str(zpath), skipped=skipped, written=written)
    return written


def extract_sources_atomic(
    zips: list[Path],
    csvs: list[Path] | None = None,
    root: Path | None = None,
) -> dict[str, Any]:
    """Extract ZIPs + fold CSVs into staging, then atomically replace ``current/``."""
    base = ensure_layout(root)
    csvs = csvs or []
    if not zips and not csvs:
        return {"ok": False, "error": "no_sources", "symbols": 0}

    with tempfile.TemporaryDirectory(dir=str(base / "tmp")) as tmp:
        staging = Path(tmp) / "extract"
        staging.mkdir(parents=True, exist_ok=True)
        extracted = 0
        for zpath in zips:
            try:
                n = _safe_extract_zip(zpath, staging)
                if n > 0:
                    extracted += 1
                else:
                    logger.warning("stooq_zip_extract_empty", path=str(zpath))
            except Exception as exc:
                logger.warning("stooq_zip_extract_failed", path=str(zpath), error=str(exc)[:160])

        csv_bars = 0
        for csv_path in csvs:
            stem = _safe_stem(csv_path.name)
            # Single-series CSVs (e.g. api_us_d.csv) land under misc/
            dest = staging / "data" / "daily" / "us" / "misc" / f"{stem}.txt"
            try:
                csv_bars += csv_to_stooq_txt(csv_path, dest)
                extracted += 1
            except Exception as exc:
                logger.warning("stooq_csv_fold_failed", path=str(csv_path), error=str(exc)[:160])

        if extracted == 0:
            return {"ok": False, "error": "extract_failed", "symbols": 0}

        index = build_symbol_index(staging)
        if not index:
            return {"ok": False, "error": "empty_index", "symbols": 0}

        current = _current_dir(base)
        backup = base / "current.bak"
        if backup.exists():
            shutil.rmtree(backup, ignore_errors=True)
        if current.exists():
            current.rename(backup)
        try:
            shutil.copytree(staging, current)
        except Exception:
            # Rollback if copy fails
            if backup.exists() and not current.exists():
                backup.rename(current)
            raise
        if backup.exists():
            shutil.rmtree(backup, ignore_errors=True)

        packages = [p.name for p in zips] + [p.name for p in csvs]
        payload = {
            "synced_at": datetime.now(timezone.utc).isoformat(),
            "packages": packages,
            "symbol_count": len(index),
            "symbols": index,
            "overwrite": True,
            "csv_bars": csv_bars,
        }
        save_manifest(payload, base)
        return {
            "ok": True,
            "symbols": len(index),
            "packages": packages,
            "synced_at": payload["synced_at"],
            "root": str(base),
            "csv_bars": csv_bars,
            "overwrite": True,
        }


# Back-compat alias
def extract_zips_atomic(zips: list[Path], root: Path | None = None) -> dict[str, Any]:
    return extract_sources_atomic(zips, csvs=None, root=root)


def stage_external_files(paths: list[Path], root: Path | None = None) -> list[Path]:
    """Copy external files into inbox with clean names (overwrite same logical package)."""
    base = ensure_layout(root)
    inbox = base / "inbox"
    staged: list[Path] = []
    for src in paths:
        src = Path(src)
        if not src.is_file():
            logger.warning("stooq_stage_missing", path=str(src))
            continue
        name = src.name
        lower = name.lower()
        # Normalize "d_world_txt (1).zip" → d_world_txt.zip
        if lower.endswith(".zip"):
            stem = _safe_stem(name)
            if stem.startswith("d_") and stem.endswith("_txt"):
                dest_name = f"{stem}.zip"
            elif "world" in stem:
                dest_name = "d_world_txt.zip"
            elif stem.startswith("d_us") or "us_txt" in stem:
                dest_name = "d_us_txt.zip"
            else:
                dest_name = f"{stem}.zip"
        elif lower.endswith(".csv"):
            dest_name = f"{_safe_stem(name)}.csv"
        else:
            dest_name = name
        dest = inbox / dest_name
        if dest.exists():
            dest.unlink()
        shutil.copy2(src, dest)
        staged.append(dest)
    return staged


async def sync_stooq_bulk(*, prefer_download: bool = True) -> dict[str, Any]:
    """Overwrite sync: download and/or inbox → replace ``current/`` → purge leftovers."""
    base = ensure_layout()
    results: list[dict[str, Any]] = []
    zips: list[Path] = []

    if prefer_download:
        for name in packages_list():
            dest = base / "downloads" / name
            info = await download_package(name, dest)
            results.append(info)
            if info.get("ok") and dest.is_file():
                zips.append(dest)

    for path in _collect_inbox_zips(base):
        # Inbox wins over same-named download (manual fresher pack)
        resolved = {p.resolve() for p in zips}
        if path.resolve() not in resolved:
            # Replace download with inbox if same package name
            zips = [z for z in zips if z.name.lower() != path.name.lower()] + [path]

    csvs = _collect_inbox_csvs(base)

    if not zips and not csvs:
        existing = load_manifest(base)
        bandwidth = any(r.get("error") == "bandwidth_limit" for r in results)
        return {
            "ok": False,
            "status": "bandwidth_limit" if bandwidth else "no_packages",
            "kept_previous": bool(existing.get("symbol_count") or existing.get("symbols")),
            "downloads": results,
            "symbol_count": int(existing.get("symbol_count") or len(existing.get("symbols") or {})),
            "synced_at": existing.get("synced_at"),
            "hint": (
                "Stooq quota hit — left previous current/ untouched. Retry tomorrow or drop ZIP into inbox."
                if bandwidth
                else (
                    "Drop d_us_txt.zip / d_world_txt.zip into "
                    f"{base / 'inbox'} or set STOOQ_COOKIE for automated download."
                )
            ),
            "root": str(base),
        }

    extract = extract_sources_atomic(zips, csvs=csvs, root=base)
    if extract.get("ok"):
        cleanup_after_sync(base, zips + csvs)
    else:
        existing = load_manifest(base)
        extract["kept_previous"] = bool(existing.get("symbol_count") or existing.get("symbols"))
    return {
        "ok": bool(extract.get("ok")),
        "status": "synced" if extract.get("ok") else "extract_failed",
        "downloads": results,
        **extract,
    }


def ingest_paths(paths: list[str | Path], *, root: Path | None = None) -> dict[str, Any]:
    """Stage external files into inbox and overwrite-sync (no HTTP)."""
    base = ensure_layout(root)
    staged = stage_external_files([Path(p) for p in paths], root=base)
    if not staged:
        return {"ok": False, "status": "no_files", "root": str(base)}
    zips = [p for p in staged if p.suffix.lower() == ".zip"]
    csvs = [p for p in staged if p.suffix.lower() == ".csv"]
    # Also pick up any other inbox siblings if user dropped more
    for z in _collect_inbox_zips(base):
        if z.resolve() not in {x.resolve() for x in zips}:
            zips.append(z)
    for c in _collect_inbox_csvs(base):
        if c.resolve() not in {x.resolve() for x in csvs}:
            csvs.append(c)
    extract = extract_sources_atomic(zips, csvs=csvs, root=base)
    if extract.get("ok"):
        cleanup_after_sync(base, zips + csvs)
    return {
        "ok": bool(extract.get("ok")),
        "status": "synced" if extract.get("ok") else "extract_failed",
        "staged": [str(p) for p in staged],
        **extract,
    }


def store_status(root: Path | None = None) -> dict[str, Any]:
    base = root or bulk_root()
    manifest = load_manifest(base)
    current = _current_dir(base)
    size_bytes = 0
    if current.is_dir():
        for f in current.rglob("*"):
            if f.is_file():
                try:
                    size_bytes += f.stat().st_size
                except OSError:
                    pass
    return {
        "root": str(base),
        "synced_at": manifest.get("synced_at"),
        "symbol_count": int(manifest.get("symbol_count") or len(manifest.get("symbols") or {})),
        "packages": manifest.get("packages") or [],
        "current_exists": current.is_dir(),
        "current_size_mb": round(size_bytes / (1024 * 1024), 1),
        "inbox_zips": [p.name for p in _collect_inbox_zips(ensure_layout(base))],
        "inbox_csvs": [p.name for p in _collect_inbox_csvs(ensure_layout(base))],
        "overwrite": True,
        "empty": size_bytes == 0 and int(manifest.get("symbol_count") or 0) == 0,
        "hint": (
            None
            if size_bytes > 0 or int(manifest.get("symbol_count") or 0) > 0
            else "Empty Stooq store — check compose mount ./backend/data/stooq → /app/data/stooq"
        ),
    }
