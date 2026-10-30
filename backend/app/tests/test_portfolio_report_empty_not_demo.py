"""GA16-303: empty book must not be flagged as demo."""

from unittest.mock import MagicMock, patch


def test_empty_book_is_not_demo():
    with (
        patch("app.services.portfolio_report.service.is_enabled", return_value=True),
        patch("app.services.portfolio_report.service.get_book") as get_book,
        patch("app.services.portfolio_report.service.compute_returns"),
        patch("app.services.portfolio_report.service.returns_as_dict", return_value={"incomplete": True}),
        patch("app.services.portfolio_report.service.compute_risk_for_user", return_value={}),
        patch("app.services.portfolio_report.service.analyze_portfolio", return_value={}),
        patch("app.services.portfolio_report.service.run_portfolio", return_value={"empty": True}),
        patch("app.services.portfolio_report.service.analyze_user", return_value={}),
        patch("app.services.portfolio_report.service.filter_wording", side_effect=lambda t, **_: t),
        patch("app.services.portfolio_report.service.render", return_value=""),
    ):
        book = MagicMock()
        book.positions.return_value = []
        get_book.return_value = book
        from app.services.portfolio_report.service import assemble

        payload = assemble(user_id="u1", mode="paper")
    assert payload["empty"] is True
    assert payload["demo"] is False
