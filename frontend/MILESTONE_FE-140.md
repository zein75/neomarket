# FE-140 — detail identifier guard

ProductDetail и CategoryDetail runtime guards теперь отклоняют payloads с пустым optional `id`. Валидные detail DTO сохраняют прежнюю поддержку отсутствующего id.

Проверка: api-types и storefront typecheck — успешно.
