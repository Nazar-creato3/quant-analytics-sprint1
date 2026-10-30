"""Merge venue credentials from repo root into backend/.env (no secret output)."""
from __future__ import annotations

import re
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ENV = ROOT / "backend" / ".env"

FIELD_MAP = {
    "BINANCE_API_KEY": "BINANCE_API_KEY",
    "BINANCE_KEY": "BINANCE_API_KEY",
    "BINANCE_API_SECRET": "BINANCE_API_SECRET",
    "BINANCE_SECRET": "BINANCE_API_SECRET",
    "BINANCE_BASE_URL": "BINANCE_BASE_URL",
    "FINAM_API_KEY": "FINAM_API_KEY",
    "FINAM_TOKEN": "FINAM_API_KEY",
    "FINAM_SECRET_KEY": "FINAM_API_KEY",
    "FINAM_ACCOUNT_ID": "FINAM_ACCOUNT_ID",
    "FINAM_ACCOUNT": "FINAM_ACCOUNT_ID",
    "FINAM_BASE_URL": "FINAM_BASE_URL",
    "FINAM_URL": "FINAM_BASE_URL",
    "TINKOFF_API_TOKEN": "TINKOFF_API_TOKEN",
    "TINKOFF_TOKEN": "TINKOFF_API_TOKEN",
    "TINKOFF_ACCOUNT_ID": "TINKOFF_ACCOUNT_ID",
    "TINKOFF_ACCOUNT": "TINKOFF_ACCOUNT_ID",
    "TINKOFF_BASE_URL": "TINKOFF_BASE_URL",
    "TINKOFF_APP_NAME": "TINKOFF_APP_NAME",
    "TINKOFF_SANDBOX": "TINKOFF_SANDBOX",
    "IBKR_API_KEY": "IBKR_API_KEY",
    "IBKR_API_SECRET": "IBKR_API_SECRET",
    "IBKR_ACCOUNT_ID": "IBKR_ACCOUNT_ID",
    "IBKR_BASE_URL": "IBKR_BASE_URL",
}

SKIP_NAMES = {
    ".gitignore", ".gitmodules", "Makefile", "README.md",
    "docker-compose.yml", "docker-compose.local.yml", "docker-compose.prod.yml",
}

DEFAULTS = {
    "BINANCE_BASE_URL": "https://testnet.binance.vision",
    "FINAM_BASE_URL": "https://trade-api.finam.ru",
    "TINKOFF_BASE_URL": "sandbox-invest-public-api.tbank.ru:443",
    "TINKOFF_APP_NAME": "QuantAnalytics",
    "TINKOFF_SANDBOX": "true",
    "STAGING_IBKR_REQUIRED": "false",
    "PAPER_TRADING_ENABLED": "true",
    "LIVE_TRADING_ENABLED": "false",
    "GRID_RUNTIME_PROFILE": "staging",
}


def _text_from_docx(path: Path) -> str:
    with zipfile.ZipFile(path) as zf:
        xml = zf.read("word/document.xml").decode("utf-8", errors="ignore")
    return re.sub(r"<[^>]+>", "\n", xml)


def parse_loose(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        for sep in ("=", ":"):
            if sep in line:
                k, _, v = line.partition(sep)
                k, v = k.strip().upper(), v.strip().strip('"').strip("'")
                if k:
                    out[k] = v
                break
    return out


def canonicalize(raw: dict[str, str]) -> dict[str, str]:
    canon: dict[str, str] = {}
    for k, v in raw.items():
        if not v:
            continue
        target = FIELD_MAP.get(k.upper())
        if target:
            canon[target] = v
    return canon


def _docx_text_parts(path: Path) -> list[str]:
    with zipfile.ZipFile(path) as zf:
        xml = zf.read("word/document.xml").decode("utf-8", errors="ignore")
    return [part.strip() for part in re.findall(r"<w:t[^>]*>([^<]*)</w:t>", xml) if part.strip()]


def parse_operator_docx(path: Path) -> dict[str, str]:
    """Parse operator keys drop (.docx) — labels vary; values mapped to canonical env names."""
    parts = _docx_text_parts(path)
    blob = "\n".join(parts)
    out: dict[str, str] = {}

    finam_match = re.search(r"tapi_sk_[A-Za-z0-9_-]+", blob)
    if finam_match:
        out["FINAM_API_KEY"] = finam_match.group(0)

    tinkoff_match = re.search(r"t\.[A-Za-z0-9_-]{20,}", blob)
    if tinkoff_match:
        out["TINKOFF_API_TOKEN"] = tinkoff_match.group(0)

    section: str | None = None
    pending_binance: list[str] = []
    secret_like = re.compile(r"^[A-Za-z0-9+/=_-]{20,}$")

    for part in parts:
        upper = part.upper()
        if "BINANCE" in upper:
            section = "binance"
            continue
        if any(tag in upper for tag in ("FINAM", "TINKOFF", "T-BANK", "TBANK", "IBKR")):
            section = upper.split()[0].lower() if part.isascii() else section
            continue
        if section == "binance" and secret_like.match(part) and not part.startswith("tapi_sk"):
            pending_binance.append(part)
        if re.fullmatch(r"\d{5,}", part):
            if section and "finam" in section:
                out.setdefault("FINAM_ACCOUNT_ID", part)
            elif section and "tinkoff" in section:
                out.setdefault("TINKOFF_ACCOUNT_ID", part)

    if pending_binance:
        out["BINANCE_API_KEY"] = pending_binance[0]
    if len(pending_binance) > 1:
        out["BINANCE_API_SECRET"] = pending_binance[1]

    return canonicalize({**parse_loose(blob), **out})


def find_sources() -> list[tuple[Path, dict[str, str]]]:
    found: list[tuple[Path, dict[str, str]]] = []
    for p in sorted(ROOT.iterdir()):
        if not p.is_file() or p.name in SKIP_NAMES:
            continue
        if p.suffix.lower() == ".docx":
            try:
                canon = parse_operator_docx(p)
            except OSError:
                continue
        elif p.suffix.lower() in {".md", ".py", ".yml", ".yaml", ".json"}:
            continue
        elif not (p.name.startswith(".env") or p.suffix.lower() in {".txt", ".env", ".ini", ".cfg", ".csv"}):
            continue
        else:
            try:
                text = p.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            canon = canonicalize(parse_loose(text))
        secret_keys = {
            k
            for k in canon
            if k not in DEFAULTS
            and not k.endswith("_BASE_URL")
            and k not in {"TINKOFF_APP_NAME", "TINKOFF_SANDBOX", "STAGING_IBKR_REQUIRED"}
        }
        if secret_keys:
            found.append((p, canon))
    found.sort(key=lambda x: (0 if x[0].name == ".env" else 1, -len(x[1])))
    return found


def merge_env(values: dict[str, str]) -> tuple[list[str], list[str]]:
    merged = {**DEFAULTS, **values}
    if "testnet.binance" not in merged.get("BINANCE_BASE_URL", ""):
        merged["BINANCE_BASE_URL"] = DEFAULTS["BINANCE_BASE_URL"]

    example = BACKEND_ENV.parent / ".env.example.local"
    lines = BACKEND_ENV.read_text(encoding="utf-8").splitlines() if BACKEND_ENV.exists() else example.read_text(encoding="utf-8").splitlines()
    out: list[str] = []
    updated: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in line:
            out.append(line)
            continue
        key = line.split("=", 1)[0].strip()
        if key in merged:
            out.append(f"{key}={merged.pop(key)}")
            updated.append(key)
        else:
            out.append(line)
    for key, val in merged.items():
        out.append(f"{key}={val}")
        updated.append(key)
    return out, updated


def main() -> int:
    sources = find_sources()
    if not sources:
        print("NO_SOURCE: no root file with venue secret fields found")
        print("Fill repo root .env with BINANCE_*, FINAM_*, TINKOFF_* then re-run")
        return 1
    src, values = sources[0]
    print(f"SOURCE: {src.name}")
    print(f"MAPPED_KEYS: {', '.join(sorted(values.keys()))}")
    out, updated = merge_env(values)
    BACKEND_ENV.write_text("\n".join(out) + "\n", encoding="utf-8")
    print(f"WROTE: backend/.env ({len(updated)} keys set/updated)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
