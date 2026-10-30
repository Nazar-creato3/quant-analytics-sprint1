# Фаза 1 — справочник, рыночные данные, книга, операции

**Слой:** Data Layer.  
**Статус:** проектный документ. Код Фазы 1 не начат.  
**ТЗ:** D-00-1 (2026-10-06) — ТЗ 1.0 заменено перечисленными документами. Оглавление: `docs/qa/QA-TZ-target-architecture.md`.  
**Приоритет:** `docs/qa/DECISIONS.md` (Р1–Р14, D-18-1), затем `docs/qa/QA-TZ-addendum-1.1.md`, набор v1.1, дополнение v1.2.  
**Аудит:** `docs/audits/analysis-validity.md`.  
**Новый хост:** `docs/ops/new-host-from-main.md`.

Формат: `LAYER_REPORT_TEMPLATE.md` + `MASTER_PROMPT.md`.

---

## Goal

Все функции данных Фазы 1 принимают **`instrument_id`**. На выходе: официальный EOD, три ценовых ряда, оценка облигаций (цена% × номинал + НКД), курсы в рубли, календарное выравнивание, корпоративные действия с ручными правками, операции брокеров включая `variation_margin`. Клиентские числа с публичных лент — `beta`, пока нет лицензии на показ.

## Scope split: Фаза 1 vs 1б

| Компонент | Фаза | Обоснование |
|---|---|---|
| Справочник инструментов | **1** | ТЗ 3.1: без `instrument_id` нельзя хранить EOD, TR, сделки |
| `instrument_eod`, корп. действия, override-таблица, FX, календари | **1** | Addendum 1.1 §§2–3 + решения 1 Oct |
| `Transaction` + адаптеры брокеров | **1** | Доходность во 2-й фазе зависит от ingest |
| **Книга позиций** (снимки holdings по `instrument_id`) | **1** | Очередь 1 отчёта: состав и концентрация. Сейчас `current_book_holdings` не канон. Снимок строится из сделок книги + broker snapshot, ключ только `instrument_id` |
| **Шина событий** (durable) | **1б** | `publish_event` в Redis pub/sub есть и **нигде не является контрактом** пайплайна. Потребители риска/отчёта появятся в Фазах 2–3. В Фазе 1 достаточно синхронной записи в таблицы + Celery job. 1б: outbox в Postgres → Redis/очередь, идемпотентность, подписчики `eod.ready`, `transaction.ingested` |

Не включать в Фазу 1: FHS VaR, TWR, единый риск-сервис для chat/terminal (Фаза 2).

## Canonical entrypoints

| Контракт | Модуль (новый) |
|---|---|
| Справочник | `app.services.instruments.registry.get(instrument_id)` / `upsert_from_venue(...)` |
| EOD | `official_close.get_eod(instrument_id, session_date, purpose=valuation\|display\|intraday)` |
| Ряды | `price_series.get_series(instrument_id, kind=raw\|split_adj\|total_return)` |
| Облигация dirty | `bonds.dirty_value(instrument_id, session_date)` |
| FX | `fx.convert(amount, from_ccy, to_ccy, on_date)` |
| Календарь | `calendars.align_asof(instrument_ids, as_of, policy=mixed_portfolio)` |
| Корп. действия | `corporate_actions.effective_actions(instrument_id)` (vendor ≪ override) |
| Книга позиций | `ledger.positions.snapshot(user_id, as_of)` |
| Операции | `ledger.transactions.ingest_venue(user_id, venue)` |
| Качество | `market_data.quality.run_daily_sample_check()` |

## Production path

1. Любой тикер → `instrument_id` (запрет хранить ряды только по строке `SBER`).  
2. Valuation: официальный close сессии; облигация → dirty (ниже).  
3. Нет официальной цены **на дату расчёта риска** → отказ `insufficient_data`, не last.  
4. Нет официальной цены **для карточки портфеля** → последняя официальная цена + `as_of` + пометка `stale_official`.  
5. Intraday last — только UI, `price_kind=last_trade`.  
6. TR-ряд: split_adj + дивиденды/купоны из effective actions.  
7. Смешанный портфель: выравнивание календарем (ниже), не «вперёд» дыр.  
8. Операции user token → `Transaction`; PLATFORM token не читает чужой счёт.

## Safety

- Reject риск: нет official EOD / нет FX на дату / нет dirty (нет номинала или НКД при необходимости).  
- Display: stale official разрешён, last trade — нет, если цель «оценка».  
- Override корп. действий: только роль staff, причина обязательна, аудит.  
- Публичный ISS/Yahoo → `license_status=beta`.  
- Isolation: операции и книга строго `user_id`.

## Tests (до включения в прод-путь)

- Резолв тикера всегда даёт `instrument_id`; EOD без id не пишется.  
- SBER LEGALCLOSE ≠ candles close (аудит).  
- Облигация: 99.5% × 1000 + НКД 12.3 = dirty.  
- Купон в TR и отдельный `Transaction` coupon.  
- `variation_margin` нормализуется с Т-Банк/MOEX FORTS.  
- Override приоритетнее ISS.  
- FX: 100 USD × USDRUB official date T.  
- Календарь: US holiday — RU день есть, US не interpolируется в риск.  
- Crypto as-of: бар UTC 00:00 ≤ cutoff.  
- Риск без EOD → None; display → stale+date.  
- Isolation user A/B.  
- `validation/` не импортируется прод-кодом.

---

## 1. Справочник инструментов (ТЗ 3.1) — обязательно в Фазе 1

**Сейчас:** `instruments` (`InstrumentORM`): `symbol+source`, `figi`, `category`, `tradable_unit`, JSON `metadata`. Резолв: `resolve_or_create_instrument` по символу.

**Нужно (канон):** одна строка = один торгуемый инструмент. Все EOD, действия, сделки, позиции ссылаются на `id`.

Минимум полей (часть уже в metadata — вынести в колонки, если без них нельзя оценить облигацию/FX):

- идентификация: `instrument_id`, `isin`, `figi`, `secid` (MOEX), venue symbols (T-Bank uid, Binance, Finam);
- класс: equity, bond, fx, crypto, future, option, index, fund;
- валюта номинала и валюта торгов;
- лот, шаг цены, board (TQBR/TQOB/RFUD…);
- облигация: номинал, дата погашения, тип НКД;
- фьючерс: код контракта, экспирация, спецификация вариационной маржи;
- статус листинга, `license_tag`.

Запрет: считать VaR/доходность по «голому» тикеру, если id не резолвится.

---

## 2. Официальная цена и отсутствие цены

RU акции/облигации: ISS history **LEGALCLOSEPRICE** (или лицензионный продукт).  
US: vendor EOD после проверки ToS. Crypto: Binance daily close = raw.

| Назначение | Нет official на дату T | Есть более старый official |
|---|---|---|
| Риск, TR, бэктест VaR | **Отказ** по инструменту / портфель `insufficient_data` | Не подставлять |
| Отображение состава портфеля | Последний official | Показать цену, **дату**, флаг `stale_official` |
| Внутридневной график | Last trade | Пометить `last_trade`, не valuation |

Таблица хранения: `instrument_eod (instrument_id, session_date, legal_close, last_close, source, license_tag)` — вариант B из прошлой редакции.

---

## 3. Облигации

Оценка позиции (валюта номинала):

`dirty = (P_official / 100) * face_value + nkd`

- `P_official` — LEGALCLOSE в **процентах номинала** (TQOB).  
- `face_value` — из справочника (ISS `FACEVALUE`).  
- `nkd` — ISS `ACCINT` на дату (накопленный купонный доход).  
Если нет `%`, номинала или НКД — для **риска** отказ; для витрины — последняя полная dirty с датой и пометкой.

Купон: в дату выплаты (или ex, как зафиксирует справочник)  
- денежный `Transaction` type=`coupon`;  
- вклад в ряд `total_return` того же `instrument_id` (реинвест в TR-индекс).

---

## 4. Валюты

Курсовые ряды — те же `instrument_eod` на FX-инструментах справочника:

- обязательный: ISS CETS `USD000UTSTOM`;  
- по мере портфеля: EUR, CNY и прочие CETS TOM/TOD, которые реально есть в книге.

`fx.convert(amount, from_ccy, to_ccy="RUB", on_date)`: official FX close даты `on_date`. Кросс через RUB, если нет прямой пары. Нет курса на дату → как нет official (риск отказ; display stale FX + дата).

---

## 5. Календари и смешанный портфель

У каждого venue — календарь сессий (Мосбиржа, US equity, crypto 24/7).

**Срез смешанного портфеля на дату T (календарный день Europe/Moscow для RU-части, иначе дата отчёта пользователя):**

- Акции/облигации RU: сессия T Мосбиржи. Нет сессии (праздник) — инструмента нет в риск-матрице этого дня (не fill-forward).  
- US equity: последняя завершённая US-сессия с `session_date <= T` в TZ биржи; если US holiday и RU торгует — US не interpolировать.  
- Крипто: дневной бар Binance с open **UTC 00:00**, который **уже закрыт** к cutoff (23:59:59 UTC даты T или явно 21:00 MSK — зафиксировать одну константу в коде и тесте; рекомендация: **UTC midnight** бар, чей `close_time <= 21:00 Europe/Moscow` даты T, чтобы не брать незакрытый день).  
- Пропуск в середине ряда: риск не выдумывает return; quality-job алерт.

Выравнивание доходностей портфеля: **inner join по датам, где все имена имеют official** (или исключение имени с дырой из дня). Не «последняя цена» внутри VaR-окна.

---

## 6. Корпоративные действия и ручные исправления

Источник: ISS (RU), лицензионный US vendor. Поля: тип, record/ex/pay, размер, валюта.

Таблица **`corporate_action_overrides`**: `id`, `instrument_id`, `matches` (isin+ex_date+type или vendor_id), patch JSON, `priority` int, `reason`, `author_user_id`, `created_at`.

Порядок effective: базовый feed, затем строки override по **убыванию priority**, затем дате. Ручная правка всегда может перебить vendor (даже меньший id — решает `priority`).

Три ряда: raw / split_adj / total_return — как в addendum; TR не Yahoo adjclose.

---

## 7. Книга позиций (Фаза 1)

Снимок: `user_id`, `as_of`, `instrument_id`, `qty`, `avg_px` (если есть), валюта, источник (`ledger` vs `broker_snapshot`). Сверка с брокером — Фаза 2 (0,1 п.п. TWR), в Фазе 1 достаточно идемпотентного снимка для очереди 1 отчёта.

---

## 8. Операции

`Transaction`: `user_id`, `venue`, `external_id`, `ts`, `type`, `instrument_id` nullable, qty, price, amount, currency, raw.

`type` включает: `trade`, `deposit`, `withdrawal`, `dividend`, `coupon`, `fee`, `tax`, **`variation_margin`** (вариационная маржа фьючерсов Мосбиржи / FORTS через Т-Банк operations), `other`.

Адаптеры: GetOperationsByCursor; Finam Trade API; Binance myTrades+deposit/withdraw; Bybit v5. Coverage min/max ts.

---

## 9. Мониторинг качества

Ежедневно: выборка 10 RU + 5 ОФЗ + 10 US + 5 crypto. Сверка official. Доля \|Δ\| > 0,5%, пропуски, устаревание, выброс без действия. Алерт; не тихий Yahoo.

---

## 10. Лицензии (решение основателя, раздел 7 addendum)

Без изменений по смыслу: КП Мосбиржи; проверить ToS FMP/Polygon; рейтинги — очередь 4; нефть/ставки — после Фазы 2. Клиентские числа с публичных лент — **бета**.

Письмо Т-Инвестиции: `docs/ops/t-invest-data-license-letter.md`.

---

## 11. Вне скоупа

Фаза 2: единый VaR/FHS/ES/Kupiec, TWR. Фаза 3: отчёт очередями, 50 ИИ-прогонов. Фаза 1б: шина. Прод на новом хосте — после выбора площадки (`docs/ops/new-host-from-main.md`).

## Residual risks

ISS без договора могут закрыть. Cursor operations короче 3 лет. LEGALCLOSE ≠ свеча на графике. Сверка идёт по документам D-00-1, не по отсутствующему тексту ТЗ 1.0.

## Next

1. Влить PR feature → main после зелёных проверок (этот шаг **не** выполнен, стоп).  
2. D-00-1 закрыт: текст ТЗ 1.0 не подставляется.  
3. КП Мосбиржи + ToS FMP/Polygon.  
4. Код: справочник → eod LEGALCLOSE → облигации/FX/календарь.
