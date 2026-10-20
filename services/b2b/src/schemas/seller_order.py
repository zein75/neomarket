from datetime import datetime, timezone
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class SellerOrderAllocationItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sku_id: UUID
    product_id: UUID
    product_title: str = Field(max_length=255)
    sku_name: str = Field(max_length=255)
    quantity: int = Field(gt=0)
    unit_price_minor: int = Field(ge=0)
    line_total_minor: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_line_total(self) -> "SellerOrderAllocationItem":
        if self.quantity * self.unit_price_minor != self.line_total_minor:
            raise ValueError("line total does not match quantity and unit price")
        return self


class SellerOrderAllocationPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    buyer_order_id: UUID
    seller_order_id: UUID
    seller_id: UUID
    currency: str = Field(min_length=3, max_length=3, pattern=r"^[A-Z]{3}$")
    status: Literal["CREATED"]
    total_minor: int = Field(ge=0)
    items: list[SellerOrderAllocationItem] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def validate_total(self) -> "SellerOrderAllocationPayload":
        if sum(item.line_total_minor for item in self.items) != self.total_minor:
            raise ValueError("seller order total does not match item snapshots")
        return self


class SellerOrderAllocationEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1]
    event_id: UUID
    event_type: Literal["seller_order.allocated.v1"]
    producer: Literal["b2c"]
    aggregate_type: Literal["seller_order"]
    aggregate_id: UUID
    aggregate_version: Literal[1]
    tenant_id: UUID
    occurred_at: datetime
    correlation_id: UUID
    payload_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    payload: SellerOrderAllocationPayload

    @field_validator("occurred_at")
    @classmethod
    def require_utc_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != timezone.utc.utcoffset(value):
            raise ValueError("occurred_at must include a UTC offset")
        return value

    @model_validator(mode="after")
    def validate_allocation_scope(self) -> "SellerOrderAllocationEvent":
        if self.aggregate_id != self.payload.seller_order_id:
            raise ValueError("aggregate id must match seller order id")
        if self.tenant_id != self.payload.seller_id:
            raise ValueError("event tenant must match seller id")
        if self.correlation_id != self.payload.buyer_order_id:
            raise ValueError("correlation id must match buyer order id")
        return self


class SellerOrderCancellationPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    buyer_order_id: UUID
    seller_order_id: UUID
    seller_id: UUID


class SellerOrderCancellationEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1]
    event_id: UUID
    event_type: Literal["seller_order.cancelled.v1"]
    producer: Literal["b2c"]
    aggregate_type: Literal["seller_order"]
    aggregate_id: UUID
    aggregate_version: Literal[2]
    tenant_id: UUID
    occurred_at: datetime
    correlation_id: UUID
    payload_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    payload: SellerOrderCancellationPayload

    @field_validator("occurred_at")
    @classmethod
    def require_utc_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != timezone.utc.utcoffset(value):
            raise ValueError("occurred_at must include a UTC offset")
        return value

    @model_validator(mode="after")
    def validate_cancellation_scope(self) -> "SellerOrderCancellationEvent":
        if self.aggregate_id != self.payload.seller_order_id:
            raise ValueError("aggregate id must match seller order id")
        if self.tenant_id != self.payload.seller_id:
            raise ValueError("event tenant must match seller id")
        if self.correlation_id != self.payload.buyer_order_id:
            raise ValueError("correlation id must match buyer order id")
        return self


class LocalCarrierWebhookPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    seller_order_id: UUID
    shipment_id: UUID
    provider_operation_ref: str = Field(min_length=1, max_length=160)


class LocalCarrierWebhookEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1]
    event_id: UUID
    event_type: Literal["shipment.dispatched.v1", "shipment.delivered.v1"]
    producer: Literal["LOCAL_TEST"]
    aggregate_type: Literal["shipment"]
    aggregate_id: UUID
    aggregate_revision: Literal[1, 2]
    tenant_id: UUID
    occurred_at: datetime
    correlation_id: UUID
    payload_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    payload: LocalCarrierWebhookPayload

    @field_validator("occurred_at")
    @classmethod
    def require_utc_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != timezone.utc.utcoffset(value):
            raise ValueError("occurred_at must include a UTC offset")
        return value

    @model_validator(mode="after")
    def validate_event_scope_and_revision(self) -> "LocalCarrierWebhookEvent":
        if self.aggregate_id != self.payload.shipment_id:
            raise ValueError("aggregate id must match shipment id")
        if self.tenant_id.int == 0 or self.correlation_id.int == 0:
            raise ValueError("tenant and correlation ids must be non-empty")
        expected_revision = 1 if self.event_type == "shipment.dispatched.v1" else 2
        if self.aggregate_revision != expected_revision:
            raise ValueError("carrier event type does not match its aggregate revision")
        return self


class CarrierWebhookResponse(BaseModel):
    event_id: UUID
    status: Literal["PENDING", "PROCESSED"]
    shipment_status: Literal["PACKED", "DISPATCHED", "DELIVERED"]


class SellerOrderItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    sku_id: UUID
    product_id: UUID
    product_title: str
    sku_name: str
    quantity: int
    unit_price_minor: int
    line_total_minor: int


class SellerPackingLineInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    seller_order_item_id: UUID
    quantity: int = Field(gt=0, le=1_000_000)


class SellerPackingCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lines: list[SellerPackingLineInput] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def reject_duplicate_items(self) -> "SellerPackingCreate":
        item_ids = [line.seller_order_item_id for line in self.lines]
        if len(item_ids) != len(set(item_ids)):
            raise ValueError("A packing manifest can contain each order line only once")
        return self


class SellerShipmentLineResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    seller_order_item_id: UUID
    quantity: int


class SellerCarrierOperationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    provider: Literal["LOCAL_TEST"]
    status: Literal["PENDING_PROVIDER", "LABEL_CREATED"]
    tracking_number: str | None
    attempts: int
    last_error: str | None
    provider_operation_ref: str
    idempotency_key: UUID


class SellerShipmentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    status: Literal["PACKED", "DISPATCHED", "DELIVERED"]
    packed_at: datetime
    lines: list[SellerShipmentLineResponse]
    carrier_operation: SellerCarrierOperationResponse | None = None


class SellerOrderResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    currency: str
    status: str
    total_minor: int
    revision: int
    allocated_at: datetime
    seller_accepted_at: datetime | None = None
    items: list[SellerOrderItemResponse]
    shipments: list[SellerShipmentResponse] = Field(default_factory=list)


class SellerOrderListResponse(BaseModel):
    items: list[SellerOrderResponse]
    page: dict[str, str | bool | None]
    as_of: datetime
