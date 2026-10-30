"""Normalized venue adapter errors (Prompt 06)."""
from __future__ import annotations


class VenueAdapterError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class WithdrawKeyRejected(VenueAdapterError):
    def __init__(self, venue: str) -> None:
        super().__init__(
            "withdraw_forbidden",
            f"{venue}: ключ с правом вывода или перевода отклонён. "
            "Создайте ключ только с торговлей и чтением счёта, без Withdraw/Transfer.",
        )
        self.venue = venue


class ReadOnlyTradeBlocked(VenueAdapterError):
    def __init__(self) -> None:
        super().__init__(
            "readonly_no_trade",
            "Токен только для чтения: аналитика доступна, торговля выключена. "
            "Торговлю нужно включить отдельным действием с торговым ключом.",
        )
