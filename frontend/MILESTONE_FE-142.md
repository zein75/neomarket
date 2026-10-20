# FE-142 — trim-aware DTO identity validation

Catalog/ProductDetail/CategoryDetail guards теперь отклоняют identifiers и titles/names, состоящие только из пробелов. Это единое правило применяется до render во всех frontend layers.

Проверка: api-client, api-types и storefront typecheck — успешно.
