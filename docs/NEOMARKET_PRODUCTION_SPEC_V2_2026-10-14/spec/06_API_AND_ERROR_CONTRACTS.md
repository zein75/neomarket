# 06 — New canonical HTTP API & stable error semantics

## API-001. Authoritative contract

Old NeoMarket canon, old protocols and previous OpenAPI are **obsolete**, never authoritative. The normative planned API is `contracts/http-b2c.openapi.yaml`, `contracts/http-b2b.openapi.yaml`, `contracts/http-admin.openapi.yaml` and events JSON schemas, plus this specification and approved ADRs. CI compares generated live OpenAPI method/path/auth/request/response/status/errors against these new files; no undocumented route enabled in production. Relative JSON Schema refs inside OpenAPI point to files in same `contracts/` directory. Production domain values `example.invalid` MUST be replaced in deployment OpenAPI server configurations; no real endpoint at these placeholder hosts.

## API-002. Boundaries / services

- **Public B2C** `/api/v1/catalog`, `/api/v1/catalog/{product_id}`; buyer auth/session provider; cart items & buyer addresses (only own), `POST /api/v1/orders` with `Idempotency-Key`, `GET /api/v1/checkout-operations/{operation_id}`, `GET /api/v1/orders[/{id}]`, `POST /api/v1/orders/{id}/cancel`. Responses include 200 idem replay, 201 committed new order, 202 persisted pending operation. See schemas for accepted fields and status types.
- **Seller B2B** `/api/v1/seller/products`, `/api/v1/seller/products/{id}`, `/skus/{id}`, `/stock-adjustments` by authorized owner; new products queued for moderation, all edits versioned; cannot set reserved_quantity or moderation state through public body; stock adjustment always ledger/audit.
- **Private Admin** `/admin/v1/moderation/tickets[/{id}]`, claim, heartbeat, release, decisions and audit; OIDC+MFA, active moderator account, claim lease/fencing. Do not expose Admin routes to public internet; never trust X-Moderator-Id.
- **Internal** `/internal/v1/inventory/reserve|unreserve|fulfill|orders/{order_id}` B2C service only; `/internal/v1/events/products`, `/events/moderation`, `/events/catalog` service-to-service with mTLS and scoped service token. No anonymous legacy `/reservations` write routes. Private route omitted from public gateway deployment.
- Public UI features outside v1 declared scope (payment methods, returns, seller settlement, invoices etc.) MUST have separate, reviewed new API schemas and gate before any UI integration. All enabled routes, including preexisting routes not in these OAS files, must be either intentionally retired or added to the new contract; no silent accidental exposures.

## API-003. Unified HTTP error contract

```json
{
  "error": {
    "code": "STOCK_BELOW_RESERVED",
    "message": "Requested stock adjustment is not available",
    "details": {"sku_id": "c2b30000-0000-4000-8000-000000000001"},
    "retryable": false
  },
  "request_id": "c2b30000-0000-4000-8000-000000000099"
}
```

Use stable codes: MALFORMED_JSON=400, AUTHENTICATION_REQUIRED=401, FORBIDDEN=403, NOT_FOUND=404, VALIDATION_ERROR=422, IDEMPOTENCY_CONFLICT / PRICE_CHANGED / INSUFFICIENT_STOCK / STOCK_BELOW_RESERVED / INVALID_STATE / ORDER_TERMINAL=409, RATE_LIMITED=429 (+Retry-After), UPSTREAM_UNAVAILABLE/DEPENDENCY_UNAVAILABLE=503, INTERNAL_ERROR=500. HTTP 401 supplies WWW-Authenticate. No SQL tracebacks, internal address, raw downstream exception, secrets or PII in response. Each response includes request_id/traceparent headers. Unknown HTTP POST result only 202 with persisted operation and Location polling, else 503 if nothing durable.

## API-004. Body/schemas/consistency

- Write Pydantic v2 extra='forbid' on unsafe operations, UUID format, bounded arrays and strings, `quantity>=1`, max 100 lines and 100 qty/line default, integer minor currency, RFC3339 UTC; maximum body 256KiB for JSON via gateway, larger uploads separate safe service.
- `reserve` canonical semantic hash derived by B2B from `(order_id,sorted sku_id quantities)`, B2C never changes order_id on retries. B2B response must include immutable authoritative unit price+currency+revision snapshot per line. B2C compares with shown/accepted cart price and initiates cancellation on mismatch.
- Stable cursor pagination, max limit 100, allowed indexes/sorts. No unbounded Python filtering of whole catalogs.
- Seller/product/buyer ownership checked per object at DB query boundary, admin routes only active principals, internal endpoints scoped per destination+operation.
- Public `Idempotency-Key` per buyer/operation. Same key+same hash -> same outcome. Same key+different hash -> 409. Race handling/retention defined in spec/03 and spec/04.

## API-005. Schema change policy

Incompatible changes -> `/api/v2` or `schema_version=2` with dual consumers, deprecation schedule and tested migration. Preprod compares all live `/openapi.json` to the target YAML; additions also require approved contract PR and regression tests. No consulting obsolete canons to infer expected endpoint behavior.

## API-006. Acceptance

API-T01 full route/security/schema diff 0 for **every** enabled handler; API-T02 standardized errors; API-T03 paginated large catalog under load; API-T04 image/protocol/JSON malformed rejection; API-T05 202 persisted checkout/poll, API-T06 200 idem replay/409 conflict; API-T07 auth ownership; API-T08 response/schema serialization; API-T09 version bump safe; API-T10 internal unexposed; API-T11 status transition policy; API-T12 controller/cloud-client timeout mapping.
