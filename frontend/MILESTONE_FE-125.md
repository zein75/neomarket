# FE-125 — strict cart totals normalization

`CartDto.itemsCount` теперь принимает только целое non-negative число, а `subtotalMinor` — только finite non-negative число. `NaN`, Infinity и отрицательные значения не проходят в UI и безопасно нормализуются в ноль.

Проверка: api-client и storefront typecheck — успешно.
