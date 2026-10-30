"""GA16-320: CryptoDataPy status must not leak exception text."""
from __future__ import annotations

from unittest.mock import patch

from app.services.crypto_stack.market import cryptodatapy_status


def test_cryptodatapy_status_hides_import_error() -> None:
    with patch.dict("sys.modules", {"cryptodatapy": None}):
        # Force ImportError path by making import raise
        import builtins

        real_import = builtins.__import__

        def _boom(name, *args, **kwargs):
            if name == "cryptodatapy":
                raise ImportError("secret module path leaked")
            return real_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=_boom):
            body = cryptodatapy_status()
    assert body["available"] is False
    assert body["error"] == "нет данных"
    assert "secret" not in str(body).lower()
