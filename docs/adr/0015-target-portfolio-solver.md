# ADR 0015 — решатель целевого портфеля

Промпт 36 просит cvxpy или аналог. В `backend/uv.lock` cvxpy нет. SciPy 1.18.1 уже записан в lock как зависимость scikit-learn 1.5.2 (также lightgbm, statsmodels, mapie, shap). Новый пакет не добавляется: прямого пина `scipy` в `requirements.txt` и `pyproject.toml` нет.

Решение: решатель — уже импортированный `scipy.optimize`. Версия та, что стоит в lock (1.18.1), без отдельной строки зависимости.

- Квадратичные задачи (среднее–дисперсия, ERC, проекция на ограничения): `scipy.optimize.minimize`, method `SLSQP`. Документация: https://docs.scipy.org/doc/scipy/reference/generated/scipy.optimize.minimize.html
- CVaR (Rockafellar–Uryasev): `scipy.optimize.linprog`, method `highs`. Документация: https://docs.scipy.org/doc/scipy/reference/generated/scipy.optimize.linprog.html
- Сжатие ковариации: `sklearn.covariance.LedoitWolf` уже прямой зависимости scikit-learn 1.5.2. https://scikit-learn.org/1.5/modules/covariance.html#shrunk-covariance

cvxpy не добавлялся. XGBoost не добавлялся. Случайности в решателе нет: старт и порядок бумаг фиксированы.

Невыполнимые ограничения возвращают `status=infeasible` и текст причины. Пустой набор весов без причины не отдаётся.
