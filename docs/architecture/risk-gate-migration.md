# Миграция проверок на единый pretrade (Prompt 10)

| Старое место | Правило сейчас | Статус |
|---|---|---|
| `orders.service.submit_manual_order` | вызывает `pretrade.evaluate` (human → warn+confirm) | подключено |
| `bots.common.record_paper_trade` | `evaluate` actor=auto → block | подключено |
| `strategy_composer.compile` | тот же `evaluate` (strategy) | каркас |
| `deal_intents.approve` | тот же `evaluate` (idea) | каркас |
| `BotRiskGuard` корреляция = тот же тикер | `duplicate_asset` по `catalog.resolve` + `stat_corr` по рядам | частично; guard ещё жив |
| `allocate_deploy_budget` / `gate_maneuver` / `desk_overlay` / `PaperExecutor` / grid create / AccessPolicy live | не удалены | тень; вызов gate на этих путях — следующий срез |
| `control_fabric.risk_gate` | ATR/intent путь | не удалять до разбора shadow |

Р2: человек — warn и подтверждение; автомат — block. Live без разрешения — block даже человеку.
