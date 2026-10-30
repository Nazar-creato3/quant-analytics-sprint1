"""Minimal YAML subset for legal/*.yaml (maps, lists, scalars, comments)."""
from __future__ import annotations

from typing import Any


def load(text: str) -> Any:
    lines = text.splitlines()
    root, _ = _parse_block(lines, 0, 0)
    return root


def _parse_block(lines: list[str], i: int, indent: int) -> tuple[Any, int]:
    mapping: dict[str, Any] = {}
    sequence: list[Any] | None = None
    while i < len(lines):
        raw = lines[i]
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            i += 1
            continue
        cur = _indent(raw)
        if cur < indent:
            break
        if cur > indent:
            raise ValueError(f"unexpected indent at line {i + 1}")
        content = raw[cur:]
        if content.startswith("- "):
            if mapping:
                raise ValueError(f"mixed map/list at line {i + 1}")
            if sequence is None:
                sequence = []
            item_text = content[2:].rstrip()
            i += 1
            if item_text.endswith(":") and not item_text.startswith('"'):
                nested, i = _parse_block(lines, i, cur + 2)
                sequence.append(nested)
            else:
                sequence.append(_scalar(item_text.split(" #", 1)[0]))
            continue
        if sequence is not None:
            break
        if ":" not in content:
            raise ValueError(f"expected key at line {i + 1}")
        key, rest = content.split(":", 1)
        key = key.strip()
        rest = rest.split(" #", 1)[0].strip()
        i += 1
        if rest in {"", "{}", "[]"}:
            if rest == "[]":
                mapping[key] = []
                continue
            if rest == "{}":
                mapping[key] = {}
                continue
            nxt = _next_content(lines, i)
            if nxt is None:
                mapping[key] = {}
            else:
                nxt_indent = _indent(lines[nxt])
                if nxt_indent > cur:
                    mapping[key], i = _parse_block(lines, i, nxt_indent)
                else:
                    mapping[key] = {}
        else:
            mapping[key] = _scalar(rest)
    if sequence is not None:
        return sequence, i
    return mapping, i


def _next_content(lines: list[str], i: int) -> int | None:
    while i < len(lines):
        stripped = lines[i].strip()
        if stripped and not stripped.startswith("#"):
            return i
        i += 1
    return None


def _indent(line: str) -> int:
    n = 0
    for ch in line:
        if ch == " ":
            n += 1
        elif ch == "\t":
            n += 2
        else:
            break
    return n


def _scalar(value: str) -> Any:
    if value in {"null", "~", "Null"}:
        return None
    if value in {"true", "True"}:
        return True
    if value in {"false", "False"}:
        return False
    if value.startswith("[") and value.endswith("]"):
        inner = value[1:-1].strip()
        if not inner:
            return []
        items = []
        buf = ""
        in_quote = False
        quote = ""
        for ch in inner:
            if in_quote:
                buf += ch
                if ch == quote:
                    in_quote = False
                continue
            if ch in {'"', "'"}:
                in_quote = True
                quote = ch
                buf += ch
                continue
            if ch == ",":
                items.append(_scalar(buf.strip()))
                buf = ""
                continue
            buf += ch
        if buf.strip():
            items.append(_scalar(buf.strip()))
        return items
    if (value.startswith('"') and value.endswith('"')) or (
        value.startswith("'") and value.endswith("'")
    ):
        return value[1:-1]
    return value
