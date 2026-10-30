# Как добавить площадку

1. Модуль `backend/app/services/venue_adapters/<venue>.py` с методами адаптера.
2. Строка в `REGISTRY` (`registry.py`): id, capabilities, history_note.
3. Фикстуры контракта в `backend/app/tests/fixtures/venues/`.
4. Нормализация операций через `ingest_operations` → книга (Prompt 05).
5. Проверка ключа через `inspect_key_permissions` — вывод/перевод запрещены.
6. Тест изоляции пользовательских токенов, если площадка мультиарендная.
