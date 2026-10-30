"""HTML tear in product layout. Numbers already computed by fund_metrics."""
from __future__ import annotations

from html import escape
from typing import Any


def render_fund_html(payload: dict[str, Any], texts: dict[str, str] | None = None) -> str:
    t = texts or {}
    fund = payload.get("fund") or {}
    title = escape(str(t.get("title") or "Как вёл себя портфель"))
    rows = "".join(
        f"<tr><td>{escape(str(c.get('ticker')))}</td>"
        f"<td>{_pct(c.get('weight'))}</td>"
        f"<td>{_pct(c.get('pct_of_vol'))}</td>"
        f"<td>{_pct(c.get('pct_of_cvar'))}</td></tr>"
        for c in (fund.get("attribution") or {}).get("components") or []
    )
    months = "".join(
        f"<li>{escape(str(m.get('year')))}-{escape(str(m.get('month')))}: {_pct(m.get('return'))}</li>"
        for m in (fund.get("monthly") or [])[:24]
    )
    return f"""<!doctype html>
<html lang="ru"><head><meta charset="utf-8"><title>{title}</title>
<style>
body{{font-family:system-ui,sans-serif;background:#0b0f14;color:#e8edf2;margin:24px}}
table{{border-collapse:collapse;width:100%}} td,th{{border:1px solid #334;padding:6px;text-align:left}}
.muted{{color:#9aa7b5;font-size:13px}}
</style></head><body>
<h1>{title}</h1>
<p>Среднегодовая {_pct(fund.get("cagr"))} · {escape(str(t.get("max_dd") or "просадка"))} {_pct(fund.get("max_dd"))} · доходность к риску {escape(str(fund.get("sharpe") if fund.get("sharpe") is not None else "нет данных"))}</p>
<p class="muted">{escape(str(t.get("basis") or ""))}</p>
<p class="muted">{escape(str(t.get("vs_k1") or ""))}</p>
<p class="muted">{_k1_lines(fund.get("k1") or {})}</p>
<h2>{escape(str(t.get("monthly") or "По месяцам"))}</h2>
<ul>{months or "<li>нет данных</li>"}</ul>
<h2>{escape(str(t.get("risk") or "Риск"))}</h2>
<p>Число независимых позиций {escape(str((fund.get("attribution") or {}).get("enb") if (fund.get("attribution") or {}).get("enb") is not None else "нет данных"))}</p>
<table><thead><tr><th>тикер</th><th>доля</th><th>доля в колебаниях</th><th>доля в хвостовом риске</th></tr></thead>
<tbody>{rows or "<tr><td colspan='4'>нет данных</td></tr>"}</tbody></table>
{_island_html("Факторы", fund.get("factors") or {})}
{_island_html("Ставка", fund.get("stress_rate") or {})}
{_island_html("Фьючерсы", fund.get("futures") or {})}
{_island_html("Цель", fund.get("goals") or {})}
{_island_html("Облигации", fund.get("bonds") or {})}
{_island_html("Выплаты", fund.get("income") or {})}
{_island_html("Сквозной взгляд", fund.get("look_through") or {})}
{_island_html("Ликвидность", fund.get("liquidity") or {})}
</body></html>"""


def _k1_lines(k1: dict[str, Any]) -> str:
    rows = k1.get("alternatives") or []
    if not rows:
        return escape(str(k1.get("reason") or "нет данных"))
    parts: list[str] = []
    for row in rows:
        ticker = str(row.get("label") or row.get("ticker") or "")
        twr = str(row.get("twr") if row.get("twr") is not None else "нет данных")
        parts.append(f"{ticker}: доходность {twr}")
    return escape(" · ".join(parts))


def _island_html(title: str, block: dict[str, Any]) -> str:
    reason = escape(str(block.get("reason") or block.get("sentence") or "нет данных"))
    status = escape(str(block.get("status") or "нет данных"))
    extra = ""
    if block.get("enb") is not None:
        extra += f" число независимых позиций {escape(str(block.get('enb')))}"
    if block.get("value_change") is not None:
        extra += f" изменение {escape(str(block.get('value_change')))}"
    if block.get("probability") is not None:
        extra += f" вероятность {escape(str(block.get('probability')))}"
    return (
        f"<h2>{escape(title)}</h2>"
        f"<p class=\"muted\">{status} · {reason}{extra}</p>"
    )


def _pct(value: Any) -> str:
    try:
        if value is None:
            return "нет данных"
        return f"{float(value) * 100:.1f}%"
    except (TypeError, ValueError):
        return "нет данных"
