# История манёвров (промпт 38)

Офлайн-прогон `run_validation`. Флаг `qa_maneuver_history`, по умолчанию включён. Откат: `FF_QA_MANEUVER_HISTORY=0` — прогон возвращает статус `off` и не пишет отчёт.

Сигнал на дату видит только цены и доходности до этой даты. Исполнение — цена следующей сессии, издержки и налоговая база — функции промпта 36. Денежный налог не считается (OQ-36-1). Генератор — `generate_maneuvers`, `target_source=user`.

Команда из каталога `backend`:

```text
python -m app.services.maneuver_history --seed 38
```

Отчёт: `docs/models/maneuvers-validation.md`. Файл для промпта 40: `docs/models/maneuver-history-control.json` (`read_control_input`). Промпт 40 этим модулем не считается.
