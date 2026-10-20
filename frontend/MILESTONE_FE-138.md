# FE-138 — ProductDetail image contract parity

`isProductDetailDto` теперь принимает `image` только как same-origin path или HTTPS URL, синхронно с catalog normalization. Небезопасный image payload считается malformed и не renderится.

Проверка: api-types и storefront typecheck — успешно.
