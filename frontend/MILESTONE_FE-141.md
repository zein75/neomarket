# FE-141 — non-empty catalog identity guard

Product card normalization теперь отклоняет empty `id` и `title` и в shared api-client, и в storefront live normalizer. Это предотвращает пустые React keys и неинформативные headings.

Проверка: api-client и storefront typecheck — успешно.
