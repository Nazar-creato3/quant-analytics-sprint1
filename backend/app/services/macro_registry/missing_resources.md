# Macro Registry gaps — data not available from confirmed free sources
#
# RESOLVED (wired via macro_source_registry):
# - CBR_KEY_RATE (cbr.ru SOAP DailyInfo)
# - FED_FUNDS_RATE, US_CPI_YOY, US_UNEMPLOYMENT, DXY, VIX (FRED US — FRED_API_KEY)
# - BRENT_OIL (FRED DCOILBRENTEU → EIA PET.RBRTE.D bulk/API → yfinance BZ=F fallback)
# - WTI_OIL (EIA PET.RWTC.D bulk/API)
# - NG_HENRY_HUB / ng_gas (EIA NG.RNGWHHD.D bulk/API)
# - HY_OAS + GOV_10Y → credit_spread (FRED BAMLH0A0HYM2 + DGS10)
# - FOMC + CBR meeting calendar (static public schedules)
# - CANADA: BOC_OVERNIGHT_RATE (BoC Valet V39079 + FRED CA IRSTCB01CAM156N fallback)
# - CANADA: CA_CPI_YOY, CA_UNEMPLOYMENT, USDCAD, CA_GOV_10Y, WTI_CANADA (FRED CA — FRED_CANADA_API_KEY)
# - WORLD BANK: WB_US/CN/RU/WLD GDP growth, WB_US inflation, WB_US current account (free API, no key)
# - WORLD BANK bulk offline: USA+CHN GDP, USA inflation via adapter:world_bank_bulk: (WORLD_BANK.zip .xls)
# - ECONOMIC CALENDAR: Investing.com via RAPIDAPI_KEY (macro calendar adapter) + Finnhub fallback
# - NEWS: NewsAPI via NEWS_API_KEY (app.services.news.client) + RSS backfill without key
#
# STILL MISSING:
# - macro_surprises / consensus_estimate (requires paid source e.g. Trading Economics)
# - RU CPI official series (Rosstat — no stable free API; FRED has limited RU coverage)
# - WB bulk for RUS/WLD GDP (not in local WORLD_BANK.zip — live API only)
# - Market expectations for next CBR/Fed/BoC decision (OIS/futures — not in free tier)
# - TradingView macro feeds (no server-side integration in repo yet)
# - BoC meeting calendar (no stable public JSON calendar endpoint wired yet)
# - EIA offline without local PET.zip/NG.zip and without EIA_API_KEY
#
# Configure in .env.example:
# FRED_API_KEY=           # St. Louis Fed — US macro series (fred_* sources)
# FRED_CANADA_API_KEY=    # St. Louis Fed — Canadian series (fred_ca_* sources)
# EIA_API_KEY=            # Optional live fallback — US energy statistics (api.eia.gov/v2/seriesid/…)
# EIA_BULK_PATH=          # Optional — directory with PET.zip, NG.zip (auto-detected from ./рыночные данные)
# RAPIDAPI_KEY=           # Investing.com economic calendar (investing_economic_calendar source)
# FINNHUB_API_KEY=          # Secondary economic calendar (app.services.macro.client)
# NEWS_API_KEY=             # NewsAPI headlines (app.services.news.client)
# GNEWS_API_KEY=            # Optional GNews supplement
# WORLD_BANK_BULK_PATH=     # Optional — directory/zip with WB bulk .xls exports
