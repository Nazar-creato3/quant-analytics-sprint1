"""List which market-data keys are configured (no secret values)."""
from __future__ import annotations

import json

from app.services.market_data.http_providers import key_configured, provider_key_flags


def main() -> None:
    try:
        flags = provider_key_flags()
    except Exception:
        names = [
            "alpaca",
            "polygon",
            "twelvedata",
            "tiingo",
            "marketstack",
            "finnhub",
            "fmp",
        ]
        flags = {n: key_configured(n) for n in names}
    print(json.dumps(flags, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
