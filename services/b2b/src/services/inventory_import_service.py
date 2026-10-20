import hashlib
import json
from datetime import datetime, timezone
from uuid import NAMESPACE_URL, UUID, uuid5

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.models.inventory_import import InventoryImportJob, InventoryImportRow
from src.models.inventory_ledger import InventoryLedger
from src.models.product import Product
from src.models.sku import SKU
from src.models.stock_adjustment import StockAdjustment
from src.schemas.inventory_import import InventoryImportCreate


class InventoryImportService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_preview(
        self, seller_id: UUID, idempotency_key: UUID, data: InventoryImportCreate
    ) -> InventoryImportJob:
        request_hash = hashlib.sha256(
            json.dumps(data.model_dump(mode="json"), sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        existing = await self._get_by_key(seller_id, str(idempotency_key))
        if existing is not None:
            return self._assert_same_request(existing, request_hash)

        wanted = {row.seller_article.casefold() for row in data.rows}
        result = await self.session.execute(
            select(SKU, Product)
            .join(Product, Product.id == SKU.product_id)
            .where(Product.seller_id == seller_id, func.lower(SKU.seller_article).in_(wanted))
            .order_by(SKU.id)
            .with_for_update(of=SKU)
        )
        candidates: dict[str, list[tuple[SKU, Product]]] = {}
        for sku, product in result.all():
            candidates.setdefault((sku.seller_article or "").casefold(), []).append((sku, product))

        job = InventoryImportJob(
            seller_id=seller_id,
            idempotency_key=str(idempotency_key),
            request_hash=request_hash,
            source_sha256=data.source_sha256.lower(),
            mode=data.mode,
            reason=data.reason,
            state="PREVIEWED",
        )
        for row_number, item in enumerate(data.rows, start=1):
            matches = candidates.get(item.seller_article.casefold(), [])
            entry = InventoryImportRow(
                row_number=row_number,
                seller_article=item.seller_article,
                target_on_hand=item.on_hand,
                state="INVALID",
                error_code=None,
                error_message=None,
            )
            if not matches:
                entry.error_code = "SKU_NOT_FOUND"
                entry.error_message = "No seller SKU matches this article"
            elif len(matches) > 1:
                entry.error_code = "SKU_ARTICLE_AMBIGUOUS"
                entry.error_message = "More than one seller SKU matches this article"
            else:
                sku, _ = matches[0]
                before = int(sku.on_hand if sku.on_hand is not None else sku.stock)
                if item.on_hand < sku.reserved_quantity:
                    entry.error_code = "BELOW_RESERVED"
                    entry.error_message = "Count cannot be lower than reserved stock"
                    entry.sku_id = sku.id
                    entry.before_on_hand = before
                    entry.expected_revision = sku.revision
                    entry.delta = item.on_hand - before
                else:
                    entry.sku_id = sku.id
                    entry.before_on_hand = before
                    entry.expected_revision = sku.revision
                    entry.delta = item.on_hand - before
                    entry.state = "UNCHANGED" if entry.delta == 0 else "VALID"
            job.rows.append(entry)

        self.session.add(job)
        try:
            await self.session.flush()
        except IntegrityError:
            await self.session.rollback()
            raced = await self._get_by_key(seller_id, str(idempotency_key))
            if raced is None:
                raise
            return self._assert_same_request(raced, request_hash)
        return job

    async def get(self, seller_id: UUID, job_id: UUID) -> InventoryImportJob:
        result = await self.session.execute(
            select(InventoryImportJob)
            .options(selectinload(InventoryImportJob.rows))
            .where(InventoryImportJob.id == job_id, InventoryImportJob.seller_id == seller_id)
        )
        job = result.scalar_one_or_none()
        if job is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"code": "IMPORT_NOT_FOUND", "message": "Inventory import was not found"},
            )
        return job

    async def commit(self, seller_id: UUID, job_id: UUID, commit_key: UUID) -> InventoryImportJob:
        result = await self.session.execute(
            select(InventoryImportJob)
            .options(selectinload(InventoryImportJob.rows))
            .where(InventoryImportJob.id == job_id, InventoryImportJob.seller_id == seller_id)
            .with_for_update()
        )
        job = result.scalar_one_or_none()
        if job is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"code": "IMPORT_NOT_FOUND", "message": "Inventory import was not found"},
            )
        if job.state != "PREVIEWED":
            if job.commit_key == str(commit_key):
                return job
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"code": "IMPORT_ALREADY_COMMITTED", "message": "Import was committed with another idempotency key"},
            )

        pending = [row for row in job.rows if row.state == "VALID" and row.sku_id is not None]
        sku_ids = [row.sku_id for row in pending]
        current: dict[UUID, SKU] = {}
        if sku_ids:
            locked = await self.session.execute(
                select(SKU)
                .join(Product, Product.id == SKU.product_id)
                .where(SKU.id.in_(sku_ids), Product.seller_id == seller_id)
                .order_by(SKU.id)
                .with_for_update(of=SKU)
            )
            current = {sku.id: sku for sku in locked.scalars().all()}

        conflict_count = 0
        applied_count = 0
        for row in sorted(pending, key=lambda item: str(item.sku_id)):
            sku = current.get(row.sku_id)
            if sku is None:
                self._conflict(row, "SKU_NOT_FOUND", "SKU is no longer available to this seller")
                conflict_count += 1
                continue
            live_on_hand = int(sku.on_hand if sku.on_hand is not None else sku.stock)
            if sku.revision != row.expected_revision or live_on_hand != row.before_on_hand:
                self._conflict(row, "STOCK_CHANGED", "Stock changed after preview; upload and preview again")
                conflict_count += 1
                continue
            if row.target_on_hand < sku.reserved_quantity:
                self._conflict(row, "BELOW_RESERVED", "Count is now lower than reserved stock")
                conflict_count += 1
                continue
            delta = row.target_on_hand - live_on_hand
            if abs(delta) > 10_000_000:
                self._conflict(row, "DELTA_OUT_OF_RANGE", "Stock change exceeds the supported adjustment limit")
                conflict_count += 1
                continue
            if delta == 0:
                row.state = "UNCHANGED"
                row.result_on_hand = live_on_hand
                continue
            adjustment_key = f"inventory-import:{job.id}:{row.row_number}"
            event_id = uuid5(NAMESPACE_URL, adjustment_key)
            adjustment_hash = hashlib.sha256(
                f"{job.id}:{row.id}:{sku.id}:{row.target_on_hand}:{job.reason}".encode()
            ).hexdigest()
            sku.on_hand = row.target_on_hand
            sku.stock = row.target_on_hand
            sku.revision += 1
            self.session.add(
                InventoryLedger(
                    event_id=event_id,
                    sku_id=sku.id,
                    delta_on_hand=delta,
                    delta_reserved=0,
                    reason="IMPORT_COUNT",
                    actor_type="SELLER",
                    actor_id=str(seller_id),
                    occurred_at=datetime.now(timezone.utc),
                    correlation_id=str(job.id),
                )
            )
            self.session.add(
                StockAdjustment(
                    sku_id=sku.id,
                    delta=delta,
                    reason=job.reason,
                    seller_id=seller_id,
                    idempotency_key=adjustment_key,
                    request_hash=adjustment_hash,
                    result_on_hand=row.target_on_hand,
                    result_reserved=sku.reserved_quantity,
                    ledger_entry_id=event_id,
                )
            )
            row.state = "APPLIED"
            row.result_on_hand = row.target_on_hand
            applied_count += 1

        has_errors = any(row.state in {"INVALID", "CONFLICT"} for row in job.rows)
        job.state = "PARTIAL" if has_errors or conflict_count else "COMMITTED"
        job.commit_key = str(commit_key)
        job.committed_at = datetime.now(timezone.utc)
        await self.session.flush()
        return job

    async def _get_by_key(self, seller_id: UUID, key: str) -> InventoryImportJob | None:
        result = await self.session.execute(
            select(InventoryImportJob)
            .options(selectinload(InventoryImportJob.rows))
            .where(InventoryImportJob.seller_id == seller_id, InventoryImportJob.idempotency_key == key)
        )
        return result.scalar_one_or_none()

    @staticmethod
    def _assert_same_request(job: InventoryImportJob, request_hash: str) -> InventoryImportJob:
        if job.request_hash != request_hash:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"code": "IDEMPOTENCY_CONFLICT", "message": "Idempotency key was used for a different import"},
            )
        return job

    @staticmethod
    def _conflict(row: InventoryImportRow, code: str, message: str) -> None:
        row.state = "CONFLICT"
        row.error_code = code
        row.error_message = message
