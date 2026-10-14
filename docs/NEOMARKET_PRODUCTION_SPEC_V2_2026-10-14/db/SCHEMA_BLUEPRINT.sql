-- NeoMarket future-state DDL BLUEPRINT (design reference ONLY)
-- WARNING: NOT a migration script. DOES NOT fit current DB without preflight/backfill.
-- Each service uses its own logical database. Sections below are alternatives;
-- production Alembic migrations must recreate them in the correct service database.
-- Enforced by DB rights and separate execution, not by a cross-DB transaction.

-- ===== B2B DATABASE =====
-- Existing skus/products tables need staged migration of old stock/price fields:
-- ALTER TABLE skus ADD COLUMN on_hand bigint;  -- nullable first, backfill, validate
-- ALTER TABLE skus ADD COLUMN price_minor bigint; ...
-- After backfill & contract: enforce constraints below with staged VALIDATE.
-- ALTER TABLE skus ADD CONSTRAINT ck_skus_on_hand_nonnegative CHECK(on_hand >= 0) NOT VALID;
-- ALTER TABLE skus ADD CONSTRAINT ck_skus_reserved_nonnegative CHECK(reserved_quantity >= 0) NOT VALID;
-- ALTER TABLE skus ADD CONSTRAINT ck_skus_reserved_le_stock CHECK(reserved_quantity <= on_hand) NOT VALID;
-- ALTER TABLE skus ADD CONSTRAINT ck_skus_price_minor CHECK(price_minor >= 0) NOT VALID;
-- Then VALIDATE, SET NOT NULL, switch code; don't blindly apply on dirty data.

CREATE TABLE IF NOT EXISTS inventory_order_lifecycle (
    order_id uuid PRIMARY KEY,
    request_fingerprint char(64),
    state varchar(16) NOT NULL DEFAULT 'NEW'
      CHECK(state IN ('NEW','RESERVED','CANCELLED','FULFILLED')),
    version bigint NOT NULL DEFAULT 0 CHECK(version>=0),
    response jsonb,
    reserved_at timestamptz,
    terminal_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT ck_inventory_lifecycle_terminal CHECK (
        (state IN ('CANCELLED','FULFILLED') AND terminal_at IS NOT NULL)
        OR (state IN ('NEW','RESERVED') AND terminal_at IS NULL)
    ),
    CONSTRAINT ck_inventory_lifecycle_hash CHECK (
        request_fingerprint IS NULL OR request_fingerprint ~ '^[a-f0-9]{64}$'
    )
);
CREATE INDEX IF NOT EXISTS idx_inventory_lifecycle_state_updated
    ON inventory_order_lifecycle(state, updated_at);

CREATE TABLE IF NOT EXISTS reservation_lines_v2 (
    id uuid PRIMARY KEY,
    order_id uuid NOT NULL REFERENCES inventory_order_lifecycle(order_id) ON DELETE RESTRICT,
    sku_id uuid NOT NULL REFERENCES skus(id) ON DELETE RESTRICT,
    quantity bigint NOT NULL CHECK(quantity>0),
    state varchar(12) NOT NULL CHECK(state IN ('ACTIVE','RELEASED','FULFILLED')),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT uq_inventory_order_sku UNIQUE(order_id,sku_id)
);
CREATE INDEX IF NOT EXISTS idx_reservation_lines_sku_state
    ON reservation_lines_v2(sku_id,state);

CREATE TABLE IF NOT EXISTS inventory_ledger (
    entry_id uuid PRIMARY KEY,
    event_id uuid NOT NULL UNIQUE,
    order_id uuid,
    sku_id uuid NOT NULL REFERENCES skus(id) ON DELETE RESTRICT,
    delta_on_hand bigint NOT NULL,
    delta_reserved bigint NOT NULL,
    reason varchar(40) NOT NULL CHECK(reason IN ('RESERVE','UNRESERVE','FULFILL','ADJUSTMENT','REPAIR')),
    actor_type varchar(20) NOT NULL,
    actor_id varchar(128) NOT NULL,
    correlation_id uuid,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT ck_ledger_not_noop CHECK(delta_on_hand<>0 OR delta_reserved<>0)
);
CREATE INDEX IF NOT EXISTS idx_inventory_ledger_sku_time ON inventory_ledger(sku_id,created_at);
CREATE INDEX IF NOT EXISTS idx_inventory_ledger_order ON inventory_ledger(order_id);

CREATE TABLE IF NOT EXISTS outbox_events_v2 (
    event_id uuid PRIMARY KEY,
    destination varchar(64) NOT NULL,
    aggregate_type varchar(64) NOT NULL,
    aggregate_id uuid NOT NULL,
    aggregate_version bigint NOT NULL CHECK(aggregate_version>=1),
    schema_version integer NOT NULL DEFAULT 1 CHECK(schema_version>=1),
    event_type varchar(100) NOT NULL,
    payload jsonb NOT NULL,
    payload_sha256 char(64) NOT NULL,
    status varchar(16) NOT NULL DEFAULT 'PENDING'
      CHECK(status IN ('PENDING','LEASED','RETRY','SENT','DEAD')),
    attempts integer NOT NULL DEFAULT 0 CHECK(attempts>=0),
    next_retry_at timestamptz NOT NULL DEFAULT now(),
    lease_owner varchar(128),
    lease_until timestamptz,
    lease_token bigint NOT NULL DEFAULT 0,
    created_at timestamptz NOT NULL DEFAULT now(),
    sent_at timestamptz,
    last_error_code varchar(100),
    correlation_id uuid
);
CREATE INDEX IF NOT EXISTS idx_outbox_claim ON outbox_events_v2(status,next_retry_at,lease_until,created_at);
CREATE INDEX IF NOT EXISTS idx_outbox_aggregate_version ON outbox_events_v2(aggregate_type,aggregate_id,aggregate_version);

CREATE TABLE IF NOT EXISTS inbox_events_v2 (
    producer varchar(64) NOT NULL,
    event_id uuid NOT NULL,
    aggregate_id uuid NOT NULL,
    aggregate_version bigint NOT NULL CHECK(aggregate_version>=1),
    payload_sha256 char(64) NOT NULL,
    process_status varchar(24) NOT NULL DEFAULT 'APPLIED'
      CHECK(process_status IN ('APPLIED','WAITING_GAP','REJECTED')),
    response jsonb,
    processed_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY(producer,event_id)
);
CREATE INDEX IF NOT EXISTS idx_inbox_event_aggregate ON inbox_events_v2(producer,aggregate_id,aggregate_version);

-- ===== B2C DATABASE (execute independently, NOT alongside B2B in same DB) =====
CREATE TABLE IF NOT EXISTS checkout_intents_v2 (
    order_id uuid PRIMARY KEY,
    buyer_id uuid NOT NULL,
    idempotency_key varchar(128) NOT NULL,
    request_fingerprint char(64) NOT NULL CHECK(request_fingerprint ~ '^[a-f0-9]{64}$'),
    request_snapshot jsonb NOT NULL,
    state varchar(24) NOT NULL CHECK(state IN (
       'NEW','RESERVING','RESERVED','COMMITTED','COMPENSATING',
       'COMPENSATED','FAILED_FINAL','RECONCILE_REQUIRED')),
    attempts integer NOT NULL DEFAULT 0 CHECK(attempts>=0),
    lease_owner varchar(128),
    lease_until timestamptz,
    fencing_token bigint NOT NULL DEFAULT 0 CHECK(fencing_token>=0),
    next_retry_at timestamptz,
    last_error_code varchar(100),
    result jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT uq_checkout_per_buyer_idem UNIQUE(buyer_id,idempotency_key)
);
CREATE INDEX IF NOT EXISTS idx_checkout_worker_claim ON checkout_intents_v2(state,next_retry_at,lease_until);
CREATE INDEX IF NOT EXISTS idx_checkout_buyer ON checkout_intents_v2(buyer_id,created_at);

CREATE TABLE IF NOT EXISTS durable_order_jobs (
    job_id uuid PRIMARY KEY,
    order_id uuid NOT NULL,
    job_type varchar(32) NOT NULL CHECK(job_type IN ('UNRESERVE','FULFILL','PAYMENT_RECONCILE')),
    state varchar(16) NOT NULL DEFAULT 'PENDING' CHECK(state IN ('PENDING','LEASED','RETRY','DONE','DEAD')),
    request_fingerprint char(64),
    attempts integer NOT NULL DEFAULT 0 CHECK(attempts>=0),
    next_retry_at timestamptz NOT NULL DEFAULT now(),
    lease_owner varchar(128),
    lease_until timestamptz,
    fencing_token bigint NOT NULL DEFAULT 0,
    last_error_code varchar(100),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT uq_one_durable_job_type UNIQUE(order_id,job_type)
);
CREATE INDEX IF NOT EXISTS idx_order_jobs_claim ON durable_order_jobs(state,next_retry_at,lease_until);

-- NOTE: B2C also needs owned outbox/inbox with same semantics as B2B,
-- but distinct physically controlled table names and DB roles.

-- ===== ADMIN DATABASE (execute independently) =====
CREATE TABLE IF NOT EXISTS moderation_tickets_v2 (
    ticket_id uuid PRIMARY KEY,
    product_id uuid NOT NULL,
    seller_id uuid NOT NULL,
    product_revision bigint NOT NULL CHECK(product_revision>=1),
    snapshot jsonb NOT NULL,
    kind varchar(16) NOT NULL CHECK(kind IN ('CREATE','EDIT','DELETE','APPEAL')),
    status varchar(20) NOT NULL CHECK(status IN (
      'PENDING','IN_REVIEW','APPROVED','BLOCKED','HARD_BLOCKED','SUPERSEDED')),
    queue_priority integer NOT NULL DEFAULT 3 CHECK(queue_priority>=0),
    moderator_id uuid,
    claim_token uuid,
    lease_until timestamptz,
    claim_fencing_token bigint NOT NULL DEFAULT 0,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT uq_moderation_ticket_product_revision_kind UNIQUE(product_id,product_revision,kind)
);
CREATE INDEX IF NOT EXISTS idx_moderation_pending ON moderation_tickets_v2(status,queue_priority DESC,created_at);
CREATE INDEX IF NOT EXISTS idx_moderation_product_revision ON moderation_tickets_v2(product_id,product_revision DESC);

CREATE TABLE IF NOT EXISTS moderation_decisions_v2 (
    decision_id uuid PRIMARY KEY,
    ticket_id uuid NOT NULL REFERENCES moderation_tickets_v2(ticket_id) ON DELETE RESTRICT,
    actor_id uuid NOT NULL,
    action varchar(16) NOT NULL CHECK(action IN ('APPROVE','BLOCK','HARD_BLOCK')),
    reason_code varchar(64),
    comment text,
    reviewed_revision bigint NOT NULL CHECK(reviewed_revision>=1),
    applied_status varchar(24) NOT NULL CHECK(applied_status IN ('PENDING_APPLY','APPLIED','STALE_DECISION')),
    created_at timestamptz NOT NULL DEFAULT now(),
    applied_at timestamptz
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_moderation_final_decision_ticket ON moderation_decisions_v2(ticket_id)
    WHERE applied_status IN ('PENDING_APPLY','APPLIED');

CREATE TABLE IF NOT EXISTS admin_audit_events_v2 (
    id uuid PRIMARY KEY,
    actor_id uuid NOT NULL,
    action varchar(100) NOT NULL,
    target_type varchar(64) NOT NULL,
    target_id uuid NOT NULL,
    before_digest varchar(64),
    after_digest varchar(64),
    reason_code varchar(64),
    correlation_id uuid NOT NULL,
    occurred_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_admin_audit_actor_time ON admin_audit_events_v2(actor_id,occurred_at DESC);

-- Append-only enforcement in actual Admin production migration:
-- Grant INSERT/SELECT, REVOKE UPDATE/DELETE/TRUNCATE for runtime role;
-- optional external digest chaining, immutable archive, controlled retention.
-- Use custom migration revision per owning DB. This blueprint intentionally
-- does not contain DROP/CASCADE/UPDATE to prevent accidental data destruction.
