# Индикаторы графика (Промпт 42)

Реализация: `app.services.market_data.indicators`. Браузер только рисует ряды.

- **SMA(n)** — среднее n закрытий включительно.
- **EMA(n)** — семя = SMA(n), затем k = 2/(n+1).
- **Bollinger(n, w)** — SMA ± w × σ, σ с делением на n (population).
- **VWAP** — накопленная typical=(H+L+C)/3 × volume / накопленный volume; нулевой volume = 1.

Свечи для графика: `get_series` / `adjust_ohlc` (raw, split_adj, total_return) из сервиса 04.
