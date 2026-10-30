# Prompt 15 — Integration status (updated 2026-07-22)

| Prompt | Status | Notes |
|--------|--------|-------|
| 10 EquityAnalytics | ✅ Merged | Used via EventRiskLayer / approval context |
| 11 EventRiskLayer | ✅ Merged | Full stream not exercised in offline replay |
| 12 CustomBasket | ✅ Merged | `services/custom_basket/` |
| 13 StrategyComposer | ✅ Merged | `services/strategy/composer/` |
| 14 AntiLossGuard | ✅ Merged | Wired via RiskGate; dedicated tests in `test_anti_loss_guard.py` |

## Data source status

| Source | Historical 90d | Notes |
|--------|----------------|-------|
| Binance | Live REST | Falls back to synthetic if API unavailable |
| MOEX | ISS candles API | Falls back to `moex_stub` synthetic |
| Tinkoff | **Read-only Invest API** | `fetch_tinkoff_bars` uses market-data candles when `TINKOFF_API_TOKEN` is set; order placement remains disabled per `VENUE_STATUS.md` |
