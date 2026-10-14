# 02 — Безопасность, идентификация, авторизация, privacy

## SEC-001. Threat model и границы доверия

Объекты: credentials, JWT/refresh tokens, seller/buyer/moderator identities, PII (телефоны, адреса), активы продавца (SKU, цены, статус), заказ/резерв, аудит модерации, DB backups, service secrets. Противники: анонимный интернет-клиент, зарегистрированный покупатель, продавец с чужими ID, скомпрометированный сервисный ключ, злонамеренный сотрудник, атакующий цепочку поставки и аварийный оператор. STRIDE: spoofing через `X-Moderator-Id`, tampering через legacy reservations/Stock update, repudiation без audit, info disclosure via open DB/error responses, denial of service через каталог/bcrypt, elevation of privilege via shared tokens.

## SEC-002. Человеческая идентификация

- Для покупателей/продавцов **MUST** проверять JWT `iss`, `aud`, `exp`, `nbf`, `iat`, `sub`, approved `alg`, `kid`, подпись JWKS; запрещены `alg=none`, fallback на известный local secret и использование неподтверждённых claims.
- Рекомендуемый путь: один OIDC провайдер (authorization code+PKCE для browser/mobile), `aud` раздельный для API, роли/тенант принадлежность проверяются на сервере. Если сохраняется локальная auth — отдельный approved ADR, независимое хранение password hash, сессии/refresh rotation, защита reset; вне `DEBUG` запуск при слабой конфигурации запрещён.
- Для администраторов обязательно SSO/OIDC с MFA (предпочтительно phishing-resistant), подтверждённая активная запись оператора в Admin DB и role-scope; `X-Moderator-Id` **не** удостоверяет identity. `actor_id` извлекается исключительно из проверенного principal.
- JWT TTL: access 10–15 мин (проектный default 15); refresh до 30 дней с rotation, хеш в БД, семейство токенов и reuse detection; logout/revoke-all и блокировка пользователя отзывают refresh, а критические операции учитывают active/revoked account по DB/инвалидируемому кэшу.
- Пароль при локальной auth: Argon2id либо сопоставимый актуальный алгоритм, параметр измеряется под нагрузкой; пароль не логировать и не хранить в plaintext; reset одноразовый, TTL <=15 мин, без account enumeration.
- Owner check на **каждый** `order_id`, `cart_id`, `address_id`, `product_id`, `sku_id`, `ticket_id`; row-scoped query или explicit 403/404 without data leakage. Разрешённые поля update перечислять явно (запрет mass assignment).

## SEC-003. Матрица RBAC/ABAC

| Операция | Guest | Buyer (owner) | Seller (owner) | Moderator | Admin/SRE svc |
|---|---|---|---|---|---|
| Public catalog | read | read | read | read | scoped read |
| Cart own | scoped ephemeral | CRUD own | no | no | support audited |
| Checkout/cancel order | no | own | no | no | operator only with separate scope + reason |
| Product/SKU edit | no | no | own | no | break-glass audited |
| Moderation claim/decision | no | no | no | assigned ticket + permission | admin role / controlled workflow |
| Moderator role management | no | no | no | no | security admin w/ MFA + dual approval |
| Internal reserve/unreserve/fulfill | no | no | no | no | only service principal `b2c-order` with granular scopes |
| Read/download backup | no | no | no | no | isolated backup operator identity |

Продавец не может изменять reserved_quantity напрямую и уменьшать on_hand ниже резерва. Модератор не может назначить себе глобальную роль или принять решение по чужому claim без explicit privileged override с аудитом.

## SEC-004. Межсервисная идентификация

- Internal requests require **mTLS + short-lived service token** with mutually verified identity (либо равносильное подтверждённое gateway/workload identity решение), `aud` specific receiver, fine-grained scopes `inventory.reserve|unreserve|fulfill`, `moderation.events.write`, `moderation.decisions.write`, `catalog.events.write`.
- Нельзя передавать один общий `X-Service-Key` всем сервисам; при миграции временно разрешить dual credentials только по IP/service identity и измеряемый sunset, после выключить.
- Validate caller, token issuer/audience/scope, replay semantics and request body; service token не переносить из фронтенда. TLS verify `true`; no `verify=False`.
- Сервисный endpoint никогда не доступен через внешний gateway; firewall/ingress default-deny, no public ports 5432/6379/8003/internal.
- Секреты в secret manager/host vault с безопасной выдачей, rotation, access auditing и kill switch. Fail-fast для пустого, известного dev/default секрета.

## SEC-005. Защита HTTP/web

- TLS 1.2+ (предпочтительно 1.3), HSTS после проверки домена, secure/same-site/httponly cookie для browser auth, CSRF при cookie-based mutations, narrowly scoped CORS allowlist, CSP и output escaping в UI.
- Per-IP/per-identity/per-scope adaptive rate limits, отдельно login/reset/registration/checkout/expensive catalog, concurrency caps, body <=256 KiB JSON (кроме upload), query cardinality limit; 429 + Retry-After.
- Request `Content-Type`, JSON nesting/depth/length, UUID, integers and images validation; лишние поля для write схем отклоняются `extra=forbid`; максимум 100 items/order (релизный default, уточнить бизнесу), max 100 qty/line с общей бизнес-границей.
- API errors: fixed safe codes, request_id, никаких stacktrace/sql/internal hostnames/JWT/reused client secrets. Логи маскируют PII, access credentials, payloads внутренних событий с PII.
- Image: только безопасные `https` CDN URLs из allowlist либо media IDs; если upload используется — max size, content sniffing, scan, isolation, transform, presigned URL TTL, запрет SVG inline и SSRF/private-IP redirects. Сервер не загружает arbitrary user URL.
- SAST/DAST, dependency/SBOM scan, CVE severity gate, секреты/PII in logs scan, external pentest до публичного запуска и после важных auth/payment changes.

## SEC-006. Хранение и право доступа к данным

- DB отдельные роли `*_runtime` (DML в своей БД), `*_migrator` (DDL controlled job), `*_readonly` для observability/backup. Никакой root/superuser из приложения; сеть БД только от своего runtime/backup.
- At-rest encrypted disks and backups, encrypted transport, secret keys separate from backup; лог доступа к backup.
- Retention by purpose: session/refresh до истечения+security retention, guest carts default 30 дней, доставленные необязательные outbox events 30 дней после подтверждения и audit, moderator decision/audit и order financial history по утверждённой правовой политике. **Не удалять terminal reservation lifecycle, пока ссылки/регуляторные требования требуют защиты от replay;** допускается compacted immutable tombstone.
- Export/deletion requests, unlink/anonymize PII without destroying order consistency; процесс доступа сотрудников и incident notification определяется юрисдикцией. Локация хранения/юридическое основание должны быть письменно определены до старта.

## SEC-007. Приёмка

SEC-T01: 100% protected endpoint negative test без credentials/с forged JWT; SEC-T02: `X-Moderator-Id` без bearer токена -> 401; SEC-T03: другой seller/user -> 403/404, 0 mutations; SEC-T04: service token wrong aud/scope -> 403; SEC-T05: JWKS rotation, token expiry/revocation; SEC-T06: brute force threshold/429; SEC-T07: нет публичного DB/admin/internal, сетевой smoke-test из внешней сети; SEC-T08: backup access isolation; SEC-T09: dynamic pentest без критических/высоких незакрытых findings. Проверяемый артефакт — CI reports + network scan + security sign-off.
