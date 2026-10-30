# ADR 0003 — pandas 3

Статус: **внедрено в 01A** (D-00A-1). Pin продукта и CI: `pandas==3.0.6`.

Источник: https://pandas.pydata.org/docs/whatsnew/v3.0.6.html  
Что ломается по умолчанию: copy-on-write; строковый dtype вместо `object`.

Проверено в репозитории: нет `dtype == 'object'` / `dtype("O")` в `backend/app`. Feature pipeline уже делает `df.copy()` (`ml/features.py`). Ядро VaR — numpy (`portfolio_math`), не pandas.

Откат: `pandas==2.2.3` в `requirements.txt`, `requirements-pipeline.txt`, убрать pin из `requirements-ci.txt`, пересобрать `requirements-ci.lock`.
