import enum
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy import JSON, DateTime, Enum, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import mapped_column, Mapped, relationship

from .base import Base, TimestampMixin

if TYPE_CHECKING:
    from .user import User


class OrderStatus(enum.Enum):
    CREATED = "CREATED"
    PAID = "PAID"
    ASSEMBLING = "ASSEMBLING"
    DELIVERING = "DELIVERING"
    DELIVERY_FINALIZING = "DELIVERY_FINALIZING"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"
    CANCEL_PENDING = "CANCEL_PENDING"


class CheckoutCompensationState(enum.Enum):
    """Durable state of an orphaned checkout-reservation recovery saga."""

    PENDING = "PENDING"
    COMPENSATING = "COMPENSATING"
    COMPENSATED = "COMPENSATED"


class CheckoutAttemptStatus(enum.Enum):
    PENDING = "PENDING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    RECONCILE_REQUIRED = "RECONCILE_REQUIRED"


class Order(Base, TimestampMixin):
    __tablename__ = "orders"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    status: Mapped[OrderStatus] = mapped_column(
        Enum(OrderStatus), default=OrderStatus.CREATED, nullable=False
    )
    total_amount: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="RUB", nullable=False)
    address_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    delivery_method: Mapped[str | None] = mapped_column(String(64), nullable=True)
    payment_method_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    contact: Mapped[dict[str, object] | None] = mapped_column(JSON, nullable=True)
    legal_consents: Mapped[list[dict[str, object]] | None] = mapped_column(JSON, nullable=True)
    quote_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    address: Mapped[dict[str, object]] = mapped_column(JSON, default=dict, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(
        String(128), unique=True, nullable=False
    )
    request_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    cancel_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancel_retry_attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    cancel_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped["User"] = relationship("User", back_populates="orders")
    items: Mapped[list["OrderItem"]] = relationship(
        "OrderItem", back_populates="order", cascade="all, delete-orphan"
    )
    status_history: Mapped[list["OrderStatusHistory"]] = relationship(
        "OrderStatusHistory", back_populates="order", cascade="all, delete-orphan"
    )


class OrderItem(Base, TimestampMixin):
    __tablename__ = "order_items"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("orders.id", ondelete="CASCADE"),
        nullable=False,
    )
    sku_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    product_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    # Nullable only for historical/legacy rows. New checkout requires the owner
    # from the authenticated B2B product snapshot before it reserves stock.
    seller_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    product_title: Mapped[str] = mapped_column(String(255), nullable=False)
    sku_name: Mapped[str] = mapped_column(String(255), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    unit_price: Mapped[int] = mapped_column(Integer, nullable=False)
    line_total: Mapped[int] = mapped_column(Integer, nullable=False)

    order: Mapped["Order"] = relationship("Order", back_populates="items")


class OrderStatusHistory(Base):
    __tablename__ = "order_status_history"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orders.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[OrderStatus] = mapped_column(Enum(OrderStatus), nullable=False)
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc), nullable=False
    )
    reason: Mapped[str | None] = mapped_column(String(500), nullable=True)

    order: Mapped["Order"] = relationship("Order", back_populates="status_history")


class PendingFulfillment(Base, TimestampMixin):
    __tablename__ = "pending_fulfillments"

    order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("orders.id", ondelete="CASCADE"),
        primary_key=True,
    )
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    next_retry_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    last_error: Mapped[str | None] = mapped_column(String(500), nullable=True)

    order: Mapped["Order"] = relationship("Order")


class PendingReservationCompensation(Base, TimestampMixin):
    """Durable checkout intent and, if needed, a compensation request.

    The row is committed *before* the reserve call.  It deliberately has no
    foreign key to ``orders``: after a crash there may be a B2B reservation
    without a local order.  A worker first checks for a committed order and
    only unreserves when no order exists.
    """

    __tablename__ = "pending_reservation_compensations"

    order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True
    )
    buyer_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, index=True
    )
    items: Mapped[list[dict[str, object]]] = mapped_column(JSON, nullable=False)
    request_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    next_retry_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # ``COMPENSATING`` is committed before calling B2B unreserve.  It is not
    # interchangeable with ``compensated_at``: a process can die after B2B
    # succeeds but before the final database commit.  A delayed checkout must
    # then be rejected rather than trusting B2B's cached reserve response.
    compensation_state: Mapped[CheckoutCompensationState] = mapped_column(
        Enum(CheckoutCompensationState, name="checkout_compensation_state"),
        default=CheckoutCompensationState.PENDING,
        nullable=False,
    )
    # A successfully compensated ambiguous reserve must remain recorded.  B2B
    # replays a reserve idempotency key even after unreserve, so deleting this
    # row would allow a late client retry to create an unpaid-for reservation.
    compensated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_error: Mapped[str | None] = mapped_column(String(500), nullable=True)


class CheckoutAttempt(Base, TimestampMixin):
    """Public durable checkout-attempt projection.

    The order and reservation tables remain the transactional source of truth;
    this owner-scoped row provides a stable status record for a lost HTTP
    response and is keyed by the same buyer/idempotency pair as the saga.
    """

    __tablename__ = "checkout_attempts"
    __table_args__ = (
        UniqueConstraint("buyer_id", "idempotency_key", name="uq_checkout_attempts_buyer_key"),
    )

    attempt_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    buyer_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), default=CheckoutAttemptStatus.PENDING.value, nullable=False
    )
    order_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(128), nullable=True)


class SellerOrderOutbox(Base, TimestampMixin):
    """B2C's durable, PII-free seller allocation delivery queue."""

    __tablename__ = "seller_order_outbox"

    event_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    seller_order_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    payload: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    payload_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="PENDING", nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(String(500), nullable=True)
