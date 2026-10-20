import hashlib
import json
from uuid import NAMESPACE_URL, uuid5
from sqlalchemy import select

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.product import Product, ProductStatus
from src.models.product_moderation_history import ProductModerationHistory
from src.models.product_version import ProductVersion
from src.repositories.outbox_event_repo import OutboxEventRepository
from src.repositories.processed_event_repo import ProcessedEventRepository
from src.repositories.product_repo import ProductRepository
from src.schemas.moderation_event import ModerationDecisionEvent
from src.services.product_service import ProductService


class ModerationEventService:
    def __init__(self, session: AsyncSession) -> None:
        self.product_repo = ProductRepository(session)
        self.processed_event_repo = ProcessedEventRepository(session)
        self.outbox_repo = OutboxEventRepository(session)

    async def apply(self, event: ModerationDecisionEvent) -> dict[str, str]:
        idempotency_key = str(event.idempotency_key)
        hash_payload = event.model_dump(mode="json")
        if event.decision_id is not None:
            # The internal Admin command carries no command timestamp. Its
            # server-assigned receipt time must not make an identical retry
            # conflict with the original durable event.
            hash_payload.pop("occurred_at", None)
        payload_hash = hashlib.sha256(
            json.dumps(
                hash_payload, sort_keys=True, separators=(",", ":")
            ).encode()
        ).hexdigest()
        if await self.processed_event_repo.exists(idempotency_key):
            get_hash = getattr(self.processed_event_repo, "get_payload_hash", None)
            if get_hash is not None:
                stored_hash = await get_hash(idempotency_key)
                if stored_hash and stored_hash != payload_hash:
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail={
                            "code": "EVENT_ID_CONFLICT",
                            "message": "event_id was reused with different payload",
                        },
                    )
            return {"status": "DUPLICATE"}
        get_for_moderation = getattr(self.product_repo, "get_for_moderation", None)
        product = await (
            get_for_moderation(event.product_id)
            if get_for_moderation is not None
            else self.product_repo.get_with_skus(event.product_id)
        )
        if not product:
            raise HTTPException(
                # The moderation endpoint declares malformed/unprocessable
                # events as 400 and deliberately does not expose product
                # existence to another service.
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "code": "PRODUCT_NOT_FOUND",
                    "message": "Product not found",
                },
            )

        decision = event.status.value
        if decision not in {
            ProductStatus.MODERATED.value,
            ProductStatus.BLOCKED.value,
        }:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "code": "INVALID_REQUEST",
                    "message": "Unsupported moderation decision",
                },
            )

        stale_revision = (
            event.reviewed_revision is not None
            and event.reviewed_revision != product.revision
        )
        if stale_revision and event.decision_id is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "REVISION_CONFLICT",
                    "message": "Moderation decision references a stale product revision",
                    "current_revision": product.revision,
                },
            )
        if stale_revision and product.revision < int(event.reviewed_revision or 0):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "REVISION_CONFLICT",
                    "message": "B2B product revision precedes the reviewed revision",
                    "current_revision": product.revision,
                },
            )
        if event.seller_id is not None and event.seller_id != product.seller_id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"code": "SELLER_MISMATCH", "message": "Decision seller does not match the product"},
            )
        if event.snapshot_hash is not None:
            version = await self.product_repo.session.scalar(
                select(ProductVersion).where(
                    ProductVersion.product_id == product.id,
                    ProductVersion.revision == event.reviewed_revision,
                )
            )
            if version is None or version.snapshot_hash != event.snapshot_hash:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail={"code": "REVISION_SNAPSHOT_CONFLICT", "message": "Reviewed revision hash does not match B2B"},
                )

        try:
            mark_processed = self.processed_event_repo.mark_processed
            try:
                await mark_processed(idempotency_key, payload_hash)
            except TypeError:
                await mark_processed(idempotency_key)
        except IntegrityError:
            rollback = getattr(self.processed_event_repo.session, "rollback", None)
            if rollback:
                await rollback()
            return {"status": "DUPLICATE"}

        if stale_revision:
            result_status = "REJECTED"
        elif decision == ProductStatus.MODERATED.value:
            await self._apply_moderated(
                product,
                event.reviewed_revision or int(getattr(product, "revision", 1)),
            )
        else:
            self._apply_blocked(product, event)
            # HARD_BLOCKED is an internal B2B terminal state.  The published
            # B2B→B2C event contract deliberately uses one unavailable-product
            # event for both soft and hard moderation blocks.
            event_type = "PRODUCT_BLOCKED"
            await self.outbox_repo.create_b2c_event(
                idempotency_key=idempotency_key,
                event_type=event_type,
                payload={
                    "event_type": event_type,
                    "idempotency_key": idempotency_key,
                    "occurred_at": event.occurred_at.isoformat(),
                    "payload": {
                        "product_id": str(product.id),
                        "sku_ids": [str(sku.id) for sku in product.skus],
                        "reason": product.status.value,
                    },
                },
            )
        if event.decision_id is not None:
            await self._queue_publication_result(
                event,
                product,
                applied=not stale_revision,
                reason_code=("REVISION_CONFLICT" if stale_revision else event.reason_code),
            )

        session = self.processed_event_repo.session
        if hasattr(session, "add"):
            session.add(
                ProductModerationHistory(
                    event_id=event.idempotency_key,
                    product_id=product.id,
                    seller_id=product.seller_id,
                    ticket_id=event.ticket_id,
                    actor_id=event.actor_id,
                    action=event.action or ("APPROVE" if decision == ProductStatus.MODERATED.value else "BLOCK"),
                    status=getattr(product.status, "value", str(product.status)),
                    reviewed_revision=event.reviewed_revision or int(getattr(product, "revision", 1)),
                    reason_code=event.reason_code,
                    comment=event.comment or (event.blocking_reason.comment if event.blocking_reason else None),
                    field_reports=[report.model_dump(mode="json") for report in (event.field_reports or [])],
                    occurred_at=event.occurred_at,
                )
            )

        await self.product_repo.session.flush()
        return {"status": result_status if stale_revision else "APPLIED"}

    async def _queue_publication_result(
        self,
        event: ModerationDecisionEvent,
        product: Product,
        *,
        applied: bool,
        reason_code: str | None,
    ) -> None:
        """Persist Admin's terminal decision result with the B2B mutation/receipt."""
        session = self.product_repo.session
        if applied:
            result_event_type = "product.publication.applied.v1"
            aggregate_version = int(event.reviewed_revision or product.revision)
        else:
            result_event_type = "product.publication.rejected.v1"
            aggregate_version = int(product.revision)
        event_id = uuid5(
            NAMESPACE_URL,
            f"neomarket:{result_event_type}:{event.decision_id}:{event.reviewed_revision}",
        )
        visible = ProductService(session)._is_publicly_visible(product)
        payload = {
            "decision_id": str(event.decision_id),
            "product_id": str(product.id),
            "submitted_revision": int(event.reviewed_revision or product.revision),
            "action": event.action or ("APPROVE" if applied else "REJECT"),
            "published_revision": product.published_revision,
            "visible": visible,
            "reason_code": reason_code,
        }
        envelope = {
            "schema_version": 1,
            "event_id": str(event_id),
            "event_type": result_event_type,
            "producer": "b2b",
            "aggregate_type": "product",
            "aggregate_id": str(product.id),
            "aggregate_version": aggregate_version,
            "occurred_at": event.occurred_at.isoformat(),
            "correlation_id": str(event.idempotency_key),
            "causation_id": str(event.decision_id),
            "payload": payload,
        }
        await self.outbox_repo.create_event(
            destination="MODERATION",
            idempotency_key=f"publication-result:{event.decision_id}",
            event_type="PRODUCT_PUBLICATION_RESULT",
            payload=envelope,
        )

    async def _apply_moderated(self, product: object, reviewed_revision: int) -> None:
        session = self.processed_event_repo.session
        if not hasattr(session, "execute") or not hasattr(session, "add"):
            product.published_revision = reviewed_revision
            product.published_snapshot = self._snapshot(product)
            product.status = ProductStatus.MODERATED
            product.is_active = True
            product.blocking_reason = None
            product.field_reports = []
            return
        snapshot = self._snapshot(product)
        snapshot_hash = hashlib.sha256(
            json.dumps(snapshot, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        existing = await session.execute(
            select(ProductVersion).where(
                ProductVersion.product_id == product.id,
                ProductVersion.revision == reviewed_revision,
            )
        )
        version = existing.scalar_one_or_none()
        if version is not None and version.snapshot_hash != snapshot_hash:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"code": "REVISION_SNAPSHOT_CONFLICT", "message": "Product revision content changed after review"},
            )
        if version is None:
            version = ProductVersion(
                product_id=product.id,
                seller_id=product.seller_id,
                revision=reviewed_revision,
                status=ProductStatus.MODERATED.value,
                snapshot=snapshot,
                snapshot_hash=snapshot_hash,
                is_published=True,
            )
            session.add(version)
        await session.execute(
            select(ProductVersion)
            .where(ProductVersion.product_id == product.id, ProductVersion.is_published.is_(True))
            .with_for_update()
        )
        await session.execute(
            ProductVersion.__table__.update()
            .where(ProductVersion.product_id == product.id)
            .values(is_published=False)
        )
        version.is_published = True
        version.status = ProductStatus.MODERATED.value
        product.published_revision = reviewed_revision
        product.published_snapshot = snapshot
        product.status = ProductStatus.MODERATED
        product.is_active = True
        product.blocking_reason = None
        product.field_reports = []

    def _snapshot(self, product: object) -> dict[str, object]:
        snapshot = {
            "title": product.title,
            "description": product.description,
            "category": product.category,
            "category_id": str(product.category_id) if product.category_id else None,
            "brand_id": str(getattr(product, "brand_id", None)) if getattr(product, "brand_id", None) else None,
            "images": list(product.images or []),
            "characteristics": dict(product.characteristics or {}),
            "skus": [
                {
                    "id": str(sku.id),
                    "name": sku.name,
                    "price": sku.price,
                    "currency": getattr(sku, "currency", "RUB"),
                    "seller_article": getattr(sku, "seller_article", None),
                    "options": getattr(sku, "options", {}) or {},
                    "images": getattr(sku, "images", []) or [],
                }
                for sku in sorted(product.skus, key=lambda item: str(item.id))
            ],
        }
        return snapshot

    def _apply_blocked(self, product: object, event: ModerationDecisionEvent) -> None:
        product.status = (
            ProductStatus.HARD_BLOCKED if event.hard_block is True else ProductStatus.BLOCKED
        )
        product.is_active = False
        product.blocking_reason = self._blocking_reason_payload(event)
        product.field_reports = [
            report.model_dump(mode="json") for report in (event.field_reports or [])
        ]

    def _blocking_reason_payload(
        self,
        event: ModerationDecisionEvent,
    ) -> dict[str, str] | None:
        if event.blocking_reason is None:
            return None
        return {
            "id": str(event.blocking_reason.id),
            "title": event.blocking_reason.title,
            "comment": event.blocking_reason.comment,
        }

    def _first_field_report_comment(
        self,
        event: ModerationDecisionEvent,
    ) -> str | None:
        for report in event.field_reports:
            if report.comment:
                return report.comment
        return None
