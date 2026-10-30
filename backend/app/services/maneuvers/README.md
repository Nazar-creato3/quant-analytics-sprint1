# Манёвры (промпт 37)

Кандидаты считает `generate_maneuvers`. Его вызывает `act_desk.propose`, когда включён `qa_maneuver_generator`.

Откат: `FF_QA_MANEUVER_GENERATOR=0` возвращает прежний список в `propose`. Live не включается (`qa_act_live` остаётся выкл.).

Влияние (VaR, ES, стресс, концентрация) берётся из `act_desk.preview_orders`, тот же путь, что проверка сделки. Налоговая база — `target_portfolio.tax` без ставки НДФЛ (OQ-36-1). Целевые доли — `target_portfolio.build_target`.

Лимит числа манёвров, срок и порог цены: `config.json`.
