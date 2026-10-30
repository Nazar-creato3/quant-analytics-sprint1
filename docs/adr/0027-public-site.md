# ADR 0027 — Публичные страницы без черновика юриста

Статус: принято 2026-10-08 (промпт 47, полоса 2).

## Контекст

Промпт 47 просит статический сайт, юридические тексты с пометкой [ЮРИСТ], SEO, Lighthouse CI и axe. Текстов основателя и юриста нет.

## Решение

1. Новые страницы лежат отдельно от кабинета `/`. Они не ходят во внутренние API.
2. Пустые места показывают «нет данных» и «ожидает текста». Черновик не публикуется.
3. Уже существующие `/legal/terms` и `/legal/privacy` этим шагом не переписываются.
4. Сторонние трекеры не добавляются. Sitemap перечисляет только публичные пути.
5. axe — `@axe-core/playwright` 4.10.2 уже в `e2e/` (не новая зависимость продукта).
6. Lighthouse CI — только GitHub Actions, `@lhci/cli@0.14.0` через `npx`, без записи в lock продукта. Бюджеты лабораторных CWV: LCP ≤ 2500 мс, CLS ≤ 0.1, категории performance/accessibility/seo ≥ 0.9.

Откат: убрать `/site` и `/methodology` из `PUBLIC_PATHS`.

Ссылки: [Lighthouse CI getting started](https://github.com/GoogleChrome/lighthouse-ci/blob/main/docs/getting-started.md); axe Playwright [API](https://github.com/dequelabs/axe-core-npm/blob/develop/packages/playwright/README.md).
