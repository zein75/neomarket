from datetime import datetime, timezone
from uuid import UUID, uuid4

from fastapi import HTTPException, status
import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.clients.b2c import B2CClient
from src.clients.moderation import ModerationClient
from src.models.product import ProductStatus
from src.models.sku import SKU
from src.models.stock_adjustment import StockAdjustment
from src.models.inventory_ledger import InventoryLedger
from src.repositories.product_repo import ProductRepository
from src.repositories.outbox_event_repo import OutboxEventRepository
from src.repositories.sku_repo import SKURepository
from src.schemas.sku import SKUCreate, SKUResponse, SKUUpdate, StockAdjustmentRequest


class SKUService:
    def __init__(self, session: AsyncSession) -> None:
        self.sku_repo = SKURepository(session)
        self.product_repo = ProductRepository(session)

    async def list_by_product(self, product_id: UUID, seller_id: UUID) -> list[SKU]:
        product = await self.product_repo.get_seller_product(product_id, seller_id)
        if not product:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Product not found"
            )
        return await self.sku_repo.list_by_product(product_id)

    async def get_for_seller(self, sku_id: UUID, seller_id: UUID) -> SKU:
        sku = await self.sku_repo.get_with_product(sku_id)
        product = getattr(sku, "product", None) if sku else None
        if sku is None or product is None or product.seller_id != seller_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="SKU not found")
        return sku

    async def get_public_sku(self, sku_id: UUID) -> dict[str, object]:
        sku = await self.sku_repo.get_with_product(sku_id)
        product = getattr(sku, "product", None) if sku else None
        if not sku or not product or not self._is_publicly_visible(product, sku):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "code": "SKU_NOT_FOUND",
                    "message": "SKU not found",
                },
            )
        return {
            "id": str(sku.id),
            "product_id": str(sku.product_id),
            "name": sku.name,
            "price": sku.price,
            "discount": getattr(sku, "discount", 0),
            "article": getattr(sku, "article", None),
            "characteristics": SKUResponse._normalize_characteristics(
                getattr(sku, "characteristics", [])
            ),
            "stock_quantity": sku.stock,
            "active_quantity": self._active_quantity(sku),
            "images": sku.images,
            "is_active": sku.is_active,
        }

    async def create(self, seller_id: UUID, data: SKUCreate) -> SKU:
        product = await self.product_repo.get_seller_product_for_update(
            data.product_id,
            seller_id,
        )
        if not product:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Product not found"
            )
        if product.status == ProductStatus.HARD_BLOCKED:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "code": "SKU_HARD_BLOCKED_PRODUCT",
                    "message": "Cannot add SKU to hard-blocked product",
                },
            )

        is_first_sku = len(product.skus) == 0
        should_send_edited = product.status in {
            ProductStatus.MODERATED,
            ProductStatus.BLOCKED,
        }
        moderation_client = ModerationClient()
        json_before = (
            moderation_client.product_snapshot(product) if should_send_edited else None
        )
        sku = await self.sku_repo.create_sku(
            product_id=data.product_id,
            name=data.name,
            price=data.price,
            stock=data.stock,
            images=[image.url for image in data.images],
        )
        if all(existing.id != sku.id for existing in product.skus):
            product.skus.append(sku)
        if is_first_sku or should_send_edited:
            product.status = ProductStatus.ON_MODERATION
            await self.sku_repo.session.flush()
        if is_first_sku:
            if hasattr(self.sku_repo.session, "add") and hasattr(
                moderation_client, "build_product_created_event"
            ):
                event = moderation_client.build_product_created_event(product)
                await OutboxEventRepository(self.sku_repo.session).create_event(
                    destination="MODERATION",
                    idempotency_key=event["idempotency_key"],
                    event_type=event["event_type"],
                    payload=event,
                )
            else:
                await moderation_client.send_product_created(product)
        elif should_send_edited and json_before is not None:
            if hasattr(self.sku_repo.session, "add") and hasattr(
                moderation_client, "build_product_edited_event"
            ):
                event = moderation_client.build_product_edited_event(
                    product, json_before=json_before
                )
                await OutboxEventRepository(self.sku_repo.session).create_event(
                    destination="MODERATION",
                    idempotency_key=event["idempotency_key"],
                    event_type=event["event_type"],
                    payload=event,
                )
            else:
                await moderation_client.send_product_edited(
                    product, json_before=json_before
                )
        return sku

    async def adjust_stock(
        self,
        sku_id: UUID,
        seller_id: UUID,
        data: StockAdjustmentRequest,
        idempotency_key: str,
    ) -> SKU:
        existing = await self.sku_repo.session.scalar(
            select(StockAdjustment).where(StockAdjustment.idempotency_key == idempotency_key)
        )
        if existing is not None:
            sku = await self.sku_repo.get_with_product(sku_id)
            if sku is None:
                raise HTTPException(status_code=404, detail="SKU not found")
            return sku
        sku = await self.sku_repo.get_for_update(sku_id)
        if sku is None:
            raise HTTPException(status_code=404, detail="SKU not found")
        product = await self.product_repo.get_seller_product(sku.product_id, seller_id)
        if product is None:
            raise HTTPException(status_code=404, detail="SKU not found")
        reserved = int(getattr(sku, "reserved_quantity", 0))
        new_stock = int(sku.stock) + data.delta
        if new_stock < reserved:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"code": "STOCK_BELOW_RESERVED", "message": "Stock cannot be lower than reserved quantity"},
            )
        sku.stock = new_stock
        if getattr(sku, "on_hand", None) is not None:
            sku.on_hand = int(sku.on_hand) + data.delta
        self.sku_repo.session.add(
            StockAdjustment(
                sku_id=sku.id,
                delta=data.delta,
                reason=data.reason,
                seller_id=seller_id,
                idempotency_key=idempotency_key,
            )
        )
        self.sku_repo.session.add(
            InventoryLedger(
                event_id=uuid4(),
                sku_id=sku.id,
                delta_on_hand=data.delta,
                delta_reserved=0,
                reason=data.reason,
                actor_type="seller",
                actor_id=str(seller_id),
                occurred_at=datetime.now(timezone.utc),
                correlation_id=str(sku.id),
            )
        )
        await self.sku_repo.session.flush()
        return sku

    async def update(self, sku_id: UUID, seller_id: UUID, data: SKUUpdate) -> SKU:
        get_for_update = getattr(
            self.sku_repo, "get_for_update", self.sku_repo.get_by_id
        )
        sku = await get_for_update(sku_id)
        if not sku:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="SKU not found"
            )
        product = await self.product_repo.get_seller_product(sku.product_id, seller_id)
        if not product:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="Access denied"
            )
        if product.status == ProductStatus.HARD_BLOCKED:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Cannot edit SKU of hard-blocked product",
            )

        moderation_client = ModerationClient()
        json_before = moderation_client.product_snapshot(product)
        if data.name is not None:
            sku.name = data.name
        price = getattr(data, "price", None)
        if price is None:
            price = getattr(data, "price_minor", None)
        if price is not None:
            sku.price = price
        stock = getattr(data, "stock", None)
        if stock is None:
            stock = getattr(data, "on_hand", None)
        if stock is not None:
            if stock < getattr(sku, "reserved_quantity", 0):
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail={
                        "code": "STOCK_BELOW_RESERVED",
                        "message": "Stock cannot be lower than reserved quantity",
                    },
                )
            previous_stock = sku.stock
            sku.stock = stock
            if getattr(sku, "on_hand", None) is not None:
                sku.on_hand = stock
            delta = stock - previous_stock
            add = getattr(self.sku_repo.session, "add", None)
            if add is not None and delta:
                add(
                    StockAdjustment(
                        sku_id=sku.id,
                        delta=delta,
                        reason="SELLER_STOCK_UPDATE",
                        seller_id=seller_id,
                    )
                )
                add(
                    InventoryLedger(
                        event_id=uuid4(),
                        sku_id=sku.id,
                        delta_on_hand=delta,
                        delta_reserved=0,
                        reason="SELLER_STOCK_UPDATE",
                        actor_type="seller",
                        actor_id=str(seller_id),
                        occurred_at=datetime.now(timezone.utc),
                        correlation_id=str(sku.id),
                    )
                )
        if data.images is not None:
            sku.images = [image.url if hasattr(image, "url") else str(image) for image in data.images]
        if data.is_active is not None:
            sku.is_active = data.is_active
        should_send_to_moderation = product.status in {
            ProductStatus.MODERATED,
            ProductStatus.BLOCKED,
        }
        if should_send_to_moderation:
            product.status = ProductStatus.ON_MODERATION
        await self.sku_repo.session.flush()
        await self.sku_repo.session.refresh(sku)
        if should_send_to_moderation:
            if hasattr(self.sku_repo.session, "add") and hasattr(
                moderation_client, "build_product_edited_event"
            ):
                event = moderation_client.build_product_edited_event(
                    product, json_before=json_before
                )
                await OutboxEventRepository(self.sku_repo.session).create_event(
                    destination="MODERATION",
                    idempotency_key=event["idempotency_key"],
                    event_type=event["event_type"],
                    payload=event,
                )
            else:
                await moderation_client.send_product_edited(
                    product, json_before=json_before
                )
        return sku

    async def delete(self, sku_id: UUID, seller_id: UUID) -> None:
        sku = await self.sku_repo.get_by_id(sku_id)
        if not sku:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="SKU not found"
            )
        product = await self.product_repo.get_seller_product(sku.product_id, seller_id)
        if not product:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="Access denied"
            )
        if product.status == ProductStatus.HARD_BLOCKED:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "code": "SKU_HARD_BLOCKED_PRODUCT",
                    "message": "Cannot delete SKU of hard-blocked product",
                },
            )
        if getattr(sku, "reserved_quantity", 0) > 0:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "SKU_ACTIVE_RESERVES",
                    "message": "Cannot delete SKU with active reserves",
                },
            )

        was_visible_in_b2c = (
            product.status == ProductStatus.MODERATED and self._active_quantity(sku) > 0
        )
        if sku in product.skus:
            product.skus.remove(sku)
        is_last_sku_deleted = len(product.skus) == 0
        await self.sku_repo.delete(sku)

        if is_last_sku_deleted and product.status == ProductStatus.ON_MODERATION:
            product.status = ProductStatus.CREATED
            await self.sku_repo.session.flush()
            moderation_client = ModerationClient()
            if hasattr(self.sku_repo.session, "add") and hasattr(
                moderation_client, "build_product_deleted_event"
            ):
                event = moderation_client.build_product_deleted_event(product)
                await OutboxEventRepository(self.sku_repo.session).create_event(
                    destination="MODERATION",
                    idempotency_key=event["idempotency_key"],
                    event_type=event["event_type"],
                    payload=event,
                )
            else:
                try:
                    await moderation_client.send_product_deleted(product)
                except httpx.HTTPError:
                    pass

        if was_visible_in_b2c:
            b2c_client = B2CClient()
            if hasattr(self.sku_repo.session, "add"):
                event = b2c_client.build_sku_out_of_stock_event(sku)
                await OutboxEventRepository(self.sku_repo.session).create_b2c_event(
                    idempotency_key=event["idempotency_key"],
                    event_type=event["event"],
                    payload={
                        "event_type": event["event"],
                        "idempotency_key": event["idempotency_key"],
                        "occurred_at": event["date"],
                        "payload": {
                            "product_id": event["product_id"],
                            "sku_ids": event["sku_ids"],
                        },
                    },
                )
            else:
                try:
                    await b2c_client.send_sku_out_of_stock(sku)
                except httpx.HTTPError:
                    pass

    def _active_quantity(self, sku: object) -> int:
        on_hand = getattr(sku, "on_hand", None)
        base = sku.stock if on_hand is None else on_hand
        return base - getattr(sku, "reserved_quantity", 0)

    def _is_publicly_visible(self, product: object, sku: object) -> bool:
        if str(product.status) != ProductStatus.MODERATED.value:
            return False
        if getattr(product, "deleted", False):
            return False
        if not getattr(sku, "is_active", False):
            return False
        return self._active_quantity(sku) > 0
