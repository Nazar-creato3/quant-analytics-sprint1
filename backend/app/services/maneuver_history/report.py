"""Validation report. Weak and strong comparisons use the same columns."""
from __future__ import annotations

from decimal import Decimal
from typing import Any

from app.services.explanations.service import filter_wording

LABELS = {
    "do_nothing": "бездействие",
    "quarterly_equal_weight": "равные веса раз в квартал",
    "target_no_views": "цель без прогнозов",
    "maneuvers": "генератор манёвров",
}
BASELINES = ("do_nothing", "quarterly_equal_weight", "target_no_views")


def _cell(value: object) -> str:
    if value is None:
        return "нет данных"
    if value == "":
        return "—"
    return str(value)


def _num(value: object) -> Decimal | None:
    if value is None or value == "" or value == "нет данных":
        return None
    return Decimal(str(value))


def _metric_row(scenario: dict[str, Any], strategy: str) -> str:
    block = scenario["strategies"][strategy]
    metrics = block["metrics"]
    cells = [
        scenario["portfolio_id"],
        scenario["profile"],
        LABELS[strategy],
        _cell(metrics.get("return_before_costs")),
        _cell(metrics.get("return_after_costs")),
        _cell(metrics.get("tax_base")),
        "не начислен",
        _cell(metrics.get("volatility")),
        _cell(metrics.get("max_drawdown")),
        _cell(metrics.get("es_975")),
        _cell(metrics.get("sharpe")),
        _cell(metrics.get("sortino")),
        _cell(metrics.get("turnover")),
        _cell(metrics.get("maneuver_frequency")),
        _cell(metrics.get("limit_breach_share")),
        _cell(block.get("note")),
    ]
    return "| " + " | ".join(cells) + " |"


def _boot_row(scenario: dict[str, Any], strategy: str) -> str:
    metrics = scenario["strategies"][strategy]["metrics"]
    mean = metrics.get("bootstrap_mean") or {}
    sharpe = metrics.get("bootstrap_sharpe") or {}
    cells = [
        scenario["portfolio_id"],
        scenario["profile"],
        LABELS[strategy],
        _cell(mean.get("low")),
        _cell(mean.get("high")),
        _cell(sharpe.get("low")),
        _cell(sharpe.get("high")),
    ]
    return "| " + " | ".join(cells) + " |"


def _pairs(result: dict[str, Any]) -> tuple[list[str], list[str], list[str]]:
    below: list[str] = []
    not_below: list[str] = []
    unknown: list[str] = []
    for scenario in result["scenarios"]:
        system = _num(scenario["strategies"]["maneuvers"]["metrics"].get("return_before_costs"))
        for name in BASELINES:
            base = _num(scenario["strategies"][name]["metrics"].get("return_before_costs"))
            note = scenario["strategies"]["maneuvers"].get("note") or ""
            base_note = scenario["strategies"][name].get("note") or ""
            cells = [
                scenario["portfolio_id"],
                scenario["profile"],
                LABELS[name],
                _cell(scenario["strategies"][name]["metrics"].get("return_before_costs")),
                _cell(scenario["strategies"]["maneuvers"]["metrics"].get("return_before_costs")),
                _cell(scenario["strategies"]["maneuvers"]["metrics"].get("sharpe")),
                _cell(scenario["strategies"][name]["metrics"].get("sharpe")),
                _cell("; ".join(item for item in (note, base_note) if item)),
            ]
            line = "| " + " | ".join(cells) + " |"
            if system is None or base is None:
                unknown.append(line)
            elif system < base:
                below.append(line)
            else:
                not_below.append(line)
    return below, not_below, unknown


def render_validation(result: dict[str, Any]) -> str:
    below, not_below, unknown = _pairs(result)
    lines = [
        "# Проверка манёвров на истории",
        "",
        f"Модель `{result['model_version']}`. Seed {result['seed']}. NumPy {result['numpy']}. SciPy {result['scipy']}.",
        "",
        "Сравнение идёт по доходности до издержек. Денежный налог не начисляется: шкала ст. 224 сверена 2026-10-06, резидентство лица не задано. После издержек число есть только если сделок не было либо тариф, спред и проскальзывание все заданы. Тарифа в `broker_costs.json` нет, поэтому у стратегий со сделками поле после издержек — «нет данных».",
        "",
        f"Окно: {result['sessions'][0]} — {result['sessions'][-1]}, сессий {len(result['sessions'])}. {result['calendar_note']}. Даты решений: {', '.join(result['decision_dates']) or 'нет данных'}.",
        "",
        f"Стартовое количество эталона умножено на {result['qty_scale']}, чтобы лот 1 не обнулял дробный остаток. Веса от этого не меняются. Пополнения, выводы, дивиденды, НКД и вариационная маржа эталона в путь не переносятся.",
        "",
        f"Заголовочная цель заранее задана как `{result['headline_method']}` без взглядов прогноза. Генератор вызывается с тем же методом и `target_source=user`. Победитель сетки параметров в заголовок не подставляется.",
        "",
        "## Кризисные окна",
        "",
        "Отдельный архив котировок не загружался. Статус — по датам в `docs/qa/golden/p*.json`.",
        "",
        "| Окно | Статус |",
        "| --- | --- |",
    ]
    for name, status in result["crisis_windows"].items():
        lines.append(f"| {name} | {status} |")
    lines.extend(
        [
            "",
            "## Справочник",
            "",
            f"Список исключений из торгов: {result['delistings']}. Имя с этой пометкой остаётся в справочнике сценария. Число выброшенных имён по всем сценариям: {sum(int(item['directory_dropped']) for item in result['scenarios'])}.",
            "",
            "## Результаты",
            "",
            "| Портфель | Профиль | Стратегия | Доходность до издержек | Доходность после издержек | Налоговая база | Налог в деньгах | Волатильность | Просадка | ES 97.5 | Шарп | Сортино | Оборот | Частота манёвров | Доля нарушений лимитов | Примечание |",
            "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
        ]
    )
    for scenario in result["scenarios"]:
        for strategy in LABELS:
            lines.append(_metric_row(scenario, strategy))
    header = "| Портфель | Профиль | База | Доходность базы до издержек | Доходность генератора до издержек | Шарп генератора | Шарп базы | Примечание |"
    rule = "| --- | --- | --- | --- | --- | --- | --- | --- |"
    lines.extend(["", "## Где генератор ниже базы", "", "Те же столбцы, что и в следующем разделе.", "", header, rule])
    lines.extend(below or ["| — | — | — | нет данных | нет данных | нет данных | нет данных | нет таких пар |"])
    lines.extend(["", "## Где генератор не ниже базы", "", header, rule])
    lines.extend(not_below or ["| — | — | — | нет данных | нет данных | нет данных | нет данных | нет таких пар |"])
    lines.extend(["", "## Сравнение без числа", "", header, rule])
    lines.extend(unknown or ["| — | — | — | нет данных | нет данных | нет данных | нет данных | нет таких пар |"])
    lines.extend(
        [
            "",
            "## Блочный бутстрап",
            "",
            "Интервал 95%, движущиеся блоки, длина округление T в степени 1/3, 200 выборок, seed от общего seed. Точка — среднее дневной доходности и годовой Шарп при безрисковой ставке 0.",
            "",
            "| Портфель | Профиль | Стратегия | Среднее, низ | Среднее, верх | Шарп, низ | Шарп, верх |",
            "| --- | --- | --- | --- | --- | --- | --- |",
        ]
    )
    for scenario in result["scenarios"]:
        for strategy in LABELS:
            lines.append(_boot_row(scenario, strategy))
    selection = result.get("parameter_selection") or {}
    lines.extend(["", "## Подбор параметров", ""])
    if selection.get("status") != "ok":
        lines.append(f"Статус: {selection.get('status', 'нет данных')}. {selection.get('reason', '')}")
    else:
        lines.append(
            f"Сетка на `{selection['portfolio_id']}`, профиль {selection['profile']}, без взглядов прогноза. "
            f"Заголовок остаётся `{selection['headline_method']}`."
        )
        lines.append("")
        lines.append("| Метод | Доходность до издержек | Шарп | Примечание |")
        lines.append("| --- | --- | --- | --- |")
        for trial in selection["trials"]:
            lines.append(
                f"| {trial['method']} | {_cell(trial['return_before_costs'])} | {_cell(trial['sharpe'])} | {_cell(trial['note'])} |"
            )
        lines.append("")
        lines.append(f"Black–Litterman без взглядов: {_cell(selection.get('black_litterman_without_views'))}.")
        dsr = selection.get("deflated_sharpe") or {}
        cscv = selection.get("cscv") or {}
        lines.append(
            f"Для статистики выбран метод с наибольшим периодовым Шарпом: `{selection.get('selected_for_statistic')}`. "
            f"Дефлированный Шарп (вероятность): {_cell(dsr.get('dsr'))}, статус {dsr.get('status')}, испытаний {dsr.get('trials', 'нет данных')}."
        )
        lines.append(
            f"Вероятность переобучения CSCV: {_cell(cscv.get('pbo'))}, статус {cscv.get('status')}, разбиений {cscv.get('splits', 'нет данных')}."
        )
    lines.extend(
        [
            "",
            "## Утечка",
            "",
            f"Решений, в сигнал которых попала дата после дня решения: {result['leak_failures']}. Point-in-time: {result['point_in_time_ok']}.",
            "",
            "Исполнение — цена следующей сессии. Эта цена в сигнал не входит. Отдельный тест подмешивает будущую дату в сигнал и обязан увидеть утечку.",
            "",
            "## Ограничения",
            "",
            "- Кризисы 2008, 2014, 2020 и 2022 в прогоне не считались, если в таблице выше стоит «нет данных». Цены этих окон не выдумывались и не скачивались.",
            "- Список бумаг, вышедших из торгов, в репозитории не найден. Помета «нет данных» не удаляет имя.",
            "- Срок жизни манёвра в генераторе ставится от часов процесса, не от даты симуляции. На следующей сессии проверяется только порог сдвига цены.",
            "- Календарь — будни, не календарь площадки.",
            "- Безрисковая ставка не задана и принята нулём в Шарпе и Сортино.",
            "- Комиссия, спред и проскальзывание не заданы. Функция издержек промпта 36 возвращает «нет данных». Денежный налог не считается.",
            "- Промпт 40 не реализован. Файл контроля лежит рядом с этим отчётом и читается `read_control_input`.",
            "",
            f"Время прогона, с: {result.get('elapsed_sec')}.",
            "",
        ]
    )
    text = "\n".join(lines)
    hits = filter_wording(text)
    if hits:
        raise ValueError("forbidden wording: " + ", ".join(hits))
    return text
