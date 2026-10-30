# Целевой портфель

Сервис `app.services.target_portfolio`. Методика: `docs/methodology/portfolio-construction.md`.
Решатель: ADR 0015 (SciPy, не cvxpy).

Промпт 37 вызывает `build_target` (тот же расчёт, что `build_for_user`). Шаг «действовать» уже кладёт результат в `target_book`.
Флаг `qa_target_portfolio`, откат `FF_QA_TARGET_PORTFOLIO=0`.
