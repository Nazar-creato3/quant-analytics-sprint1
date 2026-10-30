# ADR 0016 — проверка манёвров на истории

Промпт 38 считает walk-forward офлайн, отдельным модулем `app.services.maneuver_history`. Новый пакет не добавляется: бутстрап на NumPy, нормальные квантили и моменты — SciPy, уже записанный в `backend/uv.lock` через scikit-learn (ADR 0015).

- Сигнал режется по дате. Цена следующей сессии используется только для исполнения.
- Издержки и налоговая база — функции промпта 36. Ставка НДФЛ не задаётся (OQ-36-1). Тариф не выдумывается: пустой `broker_costs.json` даёт «нет данных».
- Генератор — `generate_maneuvers` при `target_source=user`. Режим `model` не вызывается.
- Кризисные годы не докачиваются. Нет ряда — «нет данных».
- Результат пишется в `docs/models/maneuver-history-control.json`. Промпт 40 читает `read_control_input` и в этом шаге не реализуется.

Флаг `qa_maneuver_history`. Откат: `FF_QA_MANEUVER_HISTORY=0`.

Нормальное распределение: https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.norm.html
