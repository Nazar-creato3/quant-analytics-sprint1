# Манёвры — целевая архитектура (Промпт 34)

Дата: 2026-10-06. Код в этом промпте не менялся.

Правовая рамка: решение основателя **D-18-1** (2026-10-04). Справочно (не юридическое заключение): инвестиционное консультирование — реестр Банка России; программы автоконсультирования / автоследования — аккредитация НАУФОР / СРО НФА (сообщение Банка России 09.04.2019). Рекомендация — на основании инвестиционного профиля; порядок профиля — Указание Банка России от 17.12.2018 № 5014-У. Действующую редакцию указания сверяет Промпт 35 по официальному источнику Банка России.

## 1. Карта текущего модуля

Два параллельных контура. Они не делят хранилище и не делят расчёт риска.

### 1.1 Контур QA / D-18-1 (`act_desk`)

| Что | Где |
|---|---|
| Генерация | `backend/app/services/act_desk/service.py` → `propose()` |
| Профиль / правила | `save_profile` / `save_rules` / `get_rules` (тот же файл) |
| Превью сделки | `preview_trade()` |
| Одобрение / правка / отклонение | `decide()` |
| Исполнение paper | `execute()`; live режется `qa_act_live` |
| Журнал (hash-chain, память процесса) | `_journal`, `journal_for()`, `erase_user()` |
| HTTP | `backend/app/api/v1/endpoints/act_desk.py` (`/api/v1/act/*`) |
| UI | `frontend/src/app/act/page.tsx`; вход с тикером — `CrossActions` |
| Чат | `backend/app/services/chat/tools.py` `_tool_portfolio_risk` → `journal_for` |
| Стирание | `backend/app/services/privacy/service.py` |
| Флаг | `qa_act_desk` (по умолчанию **вкл.**); `qa_act_live` **выкл.** |
| Версия модели | строка `act_desk.v1` на манёвре и записи журнала |
| Тесты | `backend/app/tests/test_act_desk.py` |

Триггер: HTTP `POST /act/propose` (кнопка / загрузка `/act`). Расписания нет.

Входы, которые **реально** читаются:

| Сервис (промпт) | Используется в `act_desk` |
|---|---|
| Книга 05 `portfolio_book` | `positions_for`, `record_transaction` при execute |
| Концентрация 14 | `analyze_portfolio` / `analyze_holdings` |
| Риск 09 `risk_engine` | `compute_risk_for_user` в превью (см. дефект D2) |
| Стресс 13 | `run_portfolio` в превью (см. дефект D2) |
| Pretrade 10 | `pretrade.policy.evaluate` в превью, kind=`idea` |
| Объяснения 16 | `render` + `filter_wording` |
| Шина 07 | `maneuver.created`, `maneuver.approved` |

Не используются в генерации: цены 04 как ряд, прогноз 11 / `forecast_core`, режим 12, поведение 15. Режим 12 подключён в **другом** контуре (`maneuver_generator` → `label_from_closes`).

### 1.2 Контур операторского пайплайна (`ManeuverGenerator`)

| Что | Где |
|---|---|
| Генерация | `backend/app/services/risk/maneuver_generator.py` `ManeuverGenerator` |
| Риск сделки | `backend/app/services/risk/engine.py` `RiskEngine` — **не** FHS `risk_engine` |
| Режим | `market_regime.service.label_from_closes` |
| ML | `app.services.ml.model.get_classifier` |
| Слоты | ровно `settings.MANEUVER_COUNT` (сейчас 10); пустые → `NO_TRADE` |
| Запись в БД | `backend/app/tasks/pipeline.py` |
| HTTP список/approve | `backend/app/api/v1/endpoints/maneuvers.py` таблица `Maneuver` |
| UI | `frontend/src/components/maneuvers/ManeuversTable.tsx`, operator `ManeuverActionBar` / `ManeuverEditModal` |
| Исполнение | `backend/app/services/execution/adapter.py`, `auto_execute.py` |
| Отмена | `backend/app/services/portfolio/cancel_maneuver.py` |
| WS | `maneuver_approved` в `websocket.py` |

Вспомогательные файлы (не SoT): `maneuver_dedupe.py`, `maneuver_diversification.py`, `maneuver_debate.py`, `maneuver_regime.py`, `maneuver_bot_guard.py`, `maneuver_presentation.py`, `pipeline/maneuver_counts.py`, `frontend/src/lib/maneuvers.ts`, `maneuver-actions.ts`.

### 1.3 Потребители (файл → функция)

| Потребитель | Контур | Файл |
|---|---|---|
| Страница «Действовать» | QA | `frontend/src/app/act/page.tsx` |
| Цикл тикера | QA | `frontend/src/components/shared/CrossActions.tsx` |
| AI Chat | QA журнал | `chat/tools.py` `_tool_portfolio_risk` |
| Оператор / таблица манёвров | pipeline | `ManeuversTable.tsx`, `endpoints/maneuvers.py` |
| Composer / боты | pipeline sizing | `bot_risk/position_sizing.py`, grid/robot (не `act_desk`) |
| Pretrade | оба частично | QA: preview idea; pipeline: ордера/боты через `pretrade.evaluate` |
| Уведомления | шина 07 | имена `maneuver.created` / `maneuver.approved`; отдельного шаблона «манёвр» в notify_center нет |
| Исполнение 24 | pipeline БД | `execution/adapter.py`; QA paper пишет в книгу `paper-act:{user}` |

## 2. Дефекты (с запуском)

Прогон 2026-10-06, локально, Python 3.14, `cd backend`. Код не менялся.

### D1. Подстановки при отсутствии данных

1. Нет анкеты → `propose` честно `empty` + причина (тест `test_propose_needs_profile`).  
2. Нет сохранённых правил → `get_rules` **подставляет** `max_single_weight=0.25`, `max_hhi=0.40`, `max_var_95=0.05`, `source=act_desk.defaults`. Запуск:

```
RULES_DEFAULT_SOURCE act_desk.defaults 0.05
```

3. `ManeuverGenerator` всегда заполняет `MANEUVER_COUNT` слотов `NO_TRADE` (модульный docstring; `settings.MANEUVER_COUNT = 10`). Пустой сигнал выглядит как манёвр.  
4. Превью: нет ценового ряда → `var_95`/`es_975` = `None`, при этом `after` копирует `before` (см. D2), стресс `-0.2` на пустом сценарии совпадает до и после.

### D2. Расхождение «проверки сделки» с ядром риска

`preview_trade` считает HHI **после** через `_holdings_plus` + `analyze_holdings`, но VaR/ES/стресс **после** снова вызывает `compute_risk_for_user` / `run_portfolio` на **текущей** книге, без гипотетической позиции.

Запуск (`preview_trade` добавить GAZP 50 к книге из SBER 10):

```
HHI {'before': '1', 'after': '0.7222222222222222222222222222'}
VAR {'before': None, 'after': None}
ES {'before': None, 'after': None}
STRESS {'before': -0.2, 'after': -0.2}
VAR_AFTER_EQ_BEFORE True
ES_AFTER_EQ_BEFORE True
STRESS_AFTER_EQ_BEFORE True
HHI_AFTER_CHANGED True
```

HHI меняется, риск и стресс — нет. `_holdings_plus` ставит **одну** цену всем бумагам.

Пайплайн считает размер через `RiskEngine` (`risk/engine.py`), UI отчёта — FHS `risk_engine`. Это разные числа на одних позициях (закрыто для UI в E46-08; генератор манёвров не переведён).

### D3. Дубли, нет гейта, нет журнала, нет версии данных

| Факт | Доказательство |
|---|---|
| Два генератора | `act_desk.propose` vs `ManeuverGenerator`; два API `/act` и `/maneuvers` |
| Два риска | `risk_engine.service` vs `risk.engine.RiskEngine` |
| Манёвр pipeline без обязательного pretrade на генерации | pretrade на ордере; слоты NO_TRADE без гейта |
| Журнал QA только в RAM | процесс перезапустился — цепочка исчезла; таблица `Maneuver` — другой объект |
| Версия алгоритма QA | только `model_version=act_desk.v1`; нет hash рядов/профиля/каталога |
| `test_act_desk.py` | 3 passed (17.15s) — paper execute и live-блок работают **внутри** RAM-контура |

## 3. Целевой конвейер

Один владелец записи манёвра: сервис `maneuvers` (вырастает из `act_desk`, не из слотов NO_TRADE). Пайплайн `ManeuverGenerator` после Промпта 37 либо вызывает этот сервис, либо уходит в shadow с датой удаления.

```
профиль (35) → целевой портфель (36) → кандидаты (37)
  → влияние = тот же расчёт, что проверка сделки (10 + 09 + 14 + 13)
  → ранжирование → объяснение (16)
  → одобрение / правка / отклонение (39)
  → pretrade (10) fail-closed
  → исполнение paper | live[ЮРИСТ] (24)
  → неизменяемый журнал (39)
  → контроль результата (40)
```

### 3.1 Контракты (логические схемы)

Общие поля каждой сущности: `schema_version` (int), `as_of` (UTC ISO), `user_id`, `mode` (`paper`|`live`), `data_status` (`ready`|`нет данных`|`partial`). Числа денег — строки Decimal. Нет данных → сущность не создаётся или `empty=true` + `reason`, **не** нули.

**InvestmentProfile (35).** Владелец: `act_desk.save_profile` → хранилище 39. Поля ядра 5014-У (сверка в 35): ожидаемая доходность, горизонт, допустимый риск; плюс запреты пользователя. Нет анкеты → кандидаты не строятся.

**TargetPortfolio (36).** Владелец: новый `target_portfolio`. Веса/тикеры из профиля + книга 05 + справочник 03. Нет цен 04 → `empty`.

**ManeuverCandidate (37).** `id`, `kind`, `legs[]` (ticker, qty, side), `expires_at`, `model_version`, `inputs_hash` (книга + профиль + ряды + режим + прогноз_log id). Влияние: скопировать `delta` из проверки сделки, не пересчитывать локально.

**ManeuverRecord (39).** Кандидат + `status` (`proposed|edited|approved|rejected|expired|executed_paper|executed_live`) + `legal_regime` (см. §4).

**TradePreview.** Контракт как сейчас у `preview_trade`, но `after.*` считается на гипотетическом составе. `gate` = `pretrade.evaluate`.

**JournalEntry (39).** Как сейчас hash-chain (`prev_hash`, `hash`, `name`, `payload`, `model_version`), хранение не в RAM: append-only таблица. События шины: существующие `maneuver.created`, `maneuver.approved`; добавить в 39 `maneuver.rejected`, `maneuver.expired`, `maneuver.executed` (не изобретать в коде 34).

Поведение при отсутствии данных на каждом шаге: не генерировать манёвр; причина в журнале и в UI (`DataState`).

## 4. Правовой режим D-18-1 (уточнение 2026-10-06)

Реализуется один режим: «манёвры по целям пользователя». Цели и лимиты — инвестиционный профиль (промпт 35). `target_source=user`. Сценарии и `user_rules` отдельными ветками не делаются.

| Что | Флаг | Состояние |
|---|---|---|
| Манёвры по целям пользователя | `qa_act_desk` | вкл.; paper; одобрение, правка или отказ; каждая заявка отдельно |
| user_rules как отдельный режим | `qa_maneuvers_user_rules` | выкл.; не развивать |
| «под профиль», `target_source=model` | `qa_act_model_profile` `[ЮРИСТ]` | выкл.; не отдельная ветка. Демо для жюри — только после 2026-10-20, стенд сейчас не собирать |
| Live | `qa_act_live` | выкл. |

Текст: «это возвращает портфель к вашим правилам» и числа последствий. Запрещены «рекомендуем», «советуем», «подходит вам», «соответствует вашему профилю». Дисклеймер базового стандарта в репозитории отсутствует (OQ-18-1); используется существующий `FORECAST_DISCLAIMER_RU`.

Откат live и выключенных режимов: флаг остаётся 0. Откат шага целиком: выключить `qa_act_desk` → API 404.

## 5. План промптов 35–41

Порядок addendum **не меняется**. Предложение основателю: D-34-1 (не блокер) — не сливать `ManeuverGenerator` в прод-UI `/act`; 37 переводит кандидатов на ядро; 39 переносит журнал из RAM.

## 6. Откат этого документа

Revert файлов `docs/architecture/maneuvers.md` и ADR 0011–0012. На рантайм не влияет.
