"""GA16-287: fund HTML must not expose CAGR/Sharpe/ENB/CVaR/TWR/P= jargon."""

from app.services.fund_report.html import render_fund_html


def test_fund_html_uses_russian_metric_labels():
    html = render_fund_html(
        {
            "fund": {
                "cagr": 0.1,
                "max_dd": -0.2,
                "sharpe": 1.2,
                "attribution": {"enb": 3.5, "components": []},
                "k1": {"alternatives": [{"label": "A", "twr": "0.05"}]},
                "factors": {"status": "ok", "reason": "x", "probability": 0.4},
            }
        }
    )
    for banned in ("CAGR", "Sharpe", "ENB", "CVaR", "TWR", "P="):
        assert banned not in html
    assert "Среднегодовая" in html
    assert "хвостовом риске" in html
    assert "вероятность" in html
