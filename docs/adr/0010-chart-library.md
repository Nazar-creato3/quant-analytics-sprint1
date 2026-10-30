# ADR 0010 — Библиотека графиков цены (Промпт 42)

Статус: принято 2026-10-05.

Решение: свечи и цена — **TradingView lightweight-charts** (Apache-2.0, пакет `lightweight-charts` ^4.2.2). На публичном графике — атрибуция TradingView.

Не цена (SHAP, track record, панели прогноза): **recharts** 2.12.7 остаётся до отдельного PR; новые OHLC-графики recharts не добавлять.

Обоснование: OHLC уже на lightweight-charts (терминал, кабинет, сетка). Две формулы индикаторов запрещены промптом 42 — расчёт SMA/EMA/Bollinger/VWAP на сервере.
