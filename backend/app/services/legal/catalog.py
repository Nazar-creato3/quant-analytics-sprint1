"""Load legal/<code>/<version>.md, hash bodies, refuse approved placeholders."""
from __future__ import annotations

import hashlib
import re
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.services.legal import yaml_lite

REPO_ROOT = Path(__file__).resolve().parents[4]


def _legal_root() -> Path:
    env = os.environ.get("LEGAL_ROOT", "").strip()
    if env:
        return Path(env)
    for candidate in (REPO_ROOT / "legal", Path("/legal"), Path("/app/legal")):
        if candidate.is_dir():
            return candidate
    return REPO_ROOT / "legal"


LEGAL_ROOT = _legal_root()

REQUIRED_CODES = (
    "terms",
    "privacy",
    "consent_pd",
    "consent_waitlist",
    "consent_marketing",
    "consent_crossborder",
    "consent_interview",
    "subscription",
)

PLACEHOLDER_RE = re.compile(r"\{\{[^{}]+\}\}")
UNFILLED_FAMILIES = (
    "operator.",
    "hosting.",
    "payments.",
    "price.",
    "exchange.",
    "exchanges.",
    "email.",
    "sms.",
    "preorder.",
    "rkn.",
)

HEADER_KEYS = ("code", "version", "effective_date", "status", "approved_by", "sha256")


class CatalogError(ValueError):
    pass


def catalog_error() -> type[CatalogError]:
    return CatalogError


def _split_md(text: str) -> tuple[dict[str, Any], str]:
    if not text.startswith("---"):
        raise CatalogError("document must start with YAML front matter")
    parts = text.split("---", 2)
    if len(parts) < 3:
        raise CatalogError("document front matter is not closed")
    meta = yaml_lite.load(parts[1])
    if not isinstance(meta, dict):
        raise CatalogError("front matter must be a mapping")
    body = parts[2].lstrip("\n")
    return meta, body


def _sha256(body: str) -> str:
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def flatten(obj: Any, prefix: str = "") -> dict[str, str]:
    out: dict[str, str] = {}
    if isinstance(obj, dict):
        for key, value in obj.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            out.update(flatten(value, path))
    elif obj is None:
        if prefix:
            out[prefix] = ""
    elif isinstance(obj, bool):
        out[prefix] = "true" if obj else "false"
    else:
        out[prefix] = str(obj)
    return out


@lru_cache(maxsize=1)
def load_operator() -> dict[str, Any]:
    path = LEGAL_ROOT / "operator.yaml"
    data = yaml_lite.load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise CatalogError("operator.yaml must be a mapping")
    return data


@lru_cache(maxsize=1)
def load_decisions() -> dict[str, str]:
    path = LEGAL_ROOT / "decisions.yaml"
    data = yaml_lite.load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise CatalogError("decisions.yaml must be a mapping")
    return {str(k): str(v) for k, v in data.items()}


@lru_cache(maxsize=1)
def load_ui_texts() -> dict[str, Any]:
    path = LEGAL_ROOT / "ui_texts.ru.yaml"
    data = yaml_lite.load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise CatalogError("ui_texts.ru.yaml must be a mapping")
    return data


def _fill(body: str, meta: dict[str, Any]) -> str:
    values = flatten(load_operator())
    values["version"] = str(meta.get("version") or "")
    values["effective_date"] = str(meta.get("effective_date") or "")
    def repl(match: re.Match[str]) -> str:
        key = match.group(0)[2:-2].strip()
        if key in values and values[key] != "" and not PLACEHOLDER_RE.fullmatch(values[key] or ""):
            return values[key]
        return match.group(0)
    return PLACEHOLDER_RE.sub(repl, body)


_MARK_RE = re.compile(r"\[(L-\d{2}):\s*([AБBАб])\]")
_LATIN = {"А": "A", "A": "A", "а": "A", "Б": "B", "B": "B", "б": "B"}


def _norm_variant(v: str) -> str:
    return _LATIN.get(v.strip()[:1], v.strip()[:1].upper())


def _chosen(key: str, variant: str, decisions: dict[str, str]) -> bool:
    current = decisions.get(key)
    if current is None:
        return True
    return _norm_variant(current) == _norm_variant(variant)


def select_variants(body: str, decisions: dict[str, str]) -> str:
    """Keep the text of the variant chosen in decisions.yaml and drop the other.

    Supported forms: a line that starts with ``[L-04:Б] ...``; inline
    alternatives ``[L-06:А] x / [L-06:Б] y``; a trailing marker on a heading.
    Markers are removed from what the reader sees.
    """
    out: list[str] = []
    for line in body.split("\n"):
        if " / [L-" in line:
            def pick(cell: str) -> str:
                parts = [p.strip() for p in cell.split(" / ")]
                marked = [p for p in parts if _MARK_RE.match(p)]
                if len(marked) < 2:
                    return cell
                keep = [p for p in parts if not _MARK_RE.match(p) or _chosen(*_MARK_RE.match(p).groups(), decisions)]
                lead = cell[: len(cell) - len(cell.lstrip())]
                trail = cell[len(cell.rstrip()):]
                return lead + " / ".join(keep) + trail
            line = "|".join(pick(c) for c in line.split("|"))
        m = _MARK_RE.match(line.strip())
        if m and line.strip().startswith(m.group(0)):
            if not _chosen(m.group(1), m.group(2), decisions):
                continue
        heading = re.match(r"^(#+ .*?)\s*(\[(L-\d{2}):\s*([AБBАб])\])\s*$", line)
        if heading and not _chosen(heading.group(3), heading.group(4), decisions):
            continue
        line = _MARK_RE.sub("", line).replace("  ", " ").rstrip()
        out.append(line.lstrip() if m else line)
    return "\n".join(out)


def render_body(body: str, meta: dict[str, Any]) -> str:
    """Text the reader sees: operator details filled, chosen variants only,
    and no template braces (an unfilled field shows as an em dash)."""
    text = select_variants(_fill(body, meta), load_decisions())
    text = re.sub(r"<!--.*?-->", "", text, flags=re.S)  # notes for the lawyer
    text = re.sub(r"(?m)^## [a-z_]+ — (.+)$", r"# \1", text)  # "## consent_pd — Title" -> "# Title"
    text = re.sub(r"(?m)^Подпись у отметки:.*\n?", "", text)  # drafting note for the UI label
    return PLACEHOLDER_RE.sub("—", text).strip() + "\n"


# Internal documents (filing drafts, procedures) are kept in the catalog but
# never served on the public site.
INTERNAL_CODES = frozenset({"rkn_notice"})


def _unfilled(text: str) -> list[str]:
    found = []
    for token in PLACEHOLDER_RE.findall(text):
        inner = token[2:-2].strip()
        if inner in {"version", "effective_date"}:
            continue
        if any(inner.startswith(fam) for fam in UNFILLED_FAMILIES):
            found.append(token)
    return found


def _read_file(path: Path) -> dict[str, Any]:
    meta, body = _split_md(path.read_text(encoding="utf-8"))
    for key in HEADER_KEYS:
        if key not in meta:
            raise CatalogError(f"{path}: missing header {key}")
    code = str(meta["code"])
    version = str(meta["version"])
    if path.parent.name != code:
        raise CatalogError(f"{path}: folder {path.parent.name} != code {code}")
    if path.stem != version:
        raise CatalogError(f"{path}: filename {path.stem} != version {version}")
    digest = _sha256(body)
    declared = str(meta.get("sha256") or "")
    if declared != digest:
        raise CatalogError(f"{path}: sha256 mismatch declared={declared} actual={digest}")
    status = str(meta.get("status") or "")
    if status not in {"draft", "approved"}:
        raise CatalogError(f"{path}: status must be draft|approved")
    filled = _fill(body, meta)
    unfilled = _unfilled(filled)
    if status == "approved" and unfilled:
        raise CatalogError(f"{path}: approved document has unfilled placeholders {unfilled}")
    latest_badge = False
    return {
        "code": code,
        "version": version,
        "effective_date": meta.get("effective_date"),
        "status": status,
        "approved_by": meta.get("approved_by"),
        "sha256": digest,
        "body": body,
        "rendered": render_body(body, meta),
        "unfilled_placeholders": unfilled,
        "path": str(path.relative_to(REPO_ROOT)),
        "latest_badge": latest_badge,
    }


@lru_cache(maxsize=1)
def _all_docs() -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    if not LEGAL_ROOT.is_dir():
        raise CatalogError("legal/ is missing")
    for path in sorted(LEGAL_ROOT.glob("*/*.md")):
        row = _read_file(path)
        grouped.setdefault(row["code"], []).append(row)
    for code, rows in grouped.items():
        rows.sort(key=lambda r: r["version"])
        rows[-1]["latest_badge"] = True
    return grouped


def reset_cache() -> None:
    load_operator.cache_clear()
    load_decisions.cache_clear()
    load_ui_texts.cache_clear()
    _all_docs.cache_clear()


def list_documents() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for code in sorted(_all_docs()):
        out.extend(_all_docs()[code])
    return out


def get_document(code: str, version: str | None = None) -> dict[str, Any] | None:
    rows = _all_docs().get(code) or []
    if not rows:
        return None
    if version is None:
        return dict(rows[-1])
    for row in rows:
        if row["version"] == version:
            return dict(row)
    return None


def validate_catalog() -> list[str]:
    errors: list[str] = []
    try:
        grouped = _all_docs()
    except CatalogError as exc:
        return [str(exc)]
    for code in REQUIRED_CODES:
        if code not in grouped:
            errors.append(f"missing required document {code}")
    ui = LEGAL_ROOT / "ui_texts.ru.yaml"
    if not ui.is_file():
        errors.append("missing legal/ui_texts.ru.yaml")
    op = LEGAL_ROOT / "operator.yaml"
    if not op.is_file():
        errors.append("missing legal/operator.yaml")
    dec = LEGAL_ROOT / "decisions.yaml"
    if not dec.is_file():
        errors.append("missing legal/decisions.yaml")
    else:
        keys = set(load_decisions())
        expected = {f"L-{i:02d}" for i in range(1, 13)}
        if keys != expected:
            errors.append(f"decisions.yaml must contain L-01..L-12, got {sorted(keys)}")
    return errors


def rkn_notice_filed() -> bool:
    operator = load_operator()
    rkn = operator.get("rkn") if isinstance(operator.get("rkn"), dict) else {}
    notice = str((rkn or {}).get("notice") or "").strip()
    return bool(notice) and not PLACEHOLDER_RE.search(notice)


def document_approved(code: str) -> bool:
    try:
        row = get_document(code)
    except CatalogError:
        return False
    return bool(row and row["status"] == "approved")
