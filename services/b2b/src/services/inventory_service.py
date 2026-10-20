from uuid import UUID

from sqlalchemy import and_, case, cast, func, or_, select, String
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.product import Product
from src.models.sku import SKU


class SellerInventoryService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_for_seller(
        self,
        seller_id: UUID,
        *,
        limit: int,
        cursor: tuple[UUID, UUID] | None = None,
        query: str | None = None,
        status_filter: str | None = None,
    ) -> dict[str, object]:
        on_hand = func.coalesce(SKU.on_hand, SKU.stock)
        statement = (
            select(
                SKU.id.label("sku_id"),
                SKU.product_id.label("product_id"),
                Product.title.label("product_title"),
                Product.category.label("category"),
                Product.status.label("status"),
                SKU.name.label("sku_name"),
                SKU.seller_article.label("seller_article"),
                on_hand.label("stock_quantity"),
                SKU.reserved_quantity.label("reserved_quantity"),
                SKU.is_active.label("is_active"),
                SKU.revision.label("revision"),
            )
            .join(Product, Product.id == SKU.product_id)
            .where(Product.seller_id == seller_id, Product.deleted.is_(False))
        )
        if query:
            search = f"%{query.strip()}%"
            statement = statement.where(
                or_(
                    Product.title.ilike(search),
                    SKU.name.ilike(search),
                    cast(SKU.id, String).ilike(search),
                )
            )
        if status_filter == "available":
            statement = statement.where(SKU.is_active.is_(True), on_hand > SKU.reserved_quantity)
        elif status_filter == "reserved":
            statement = statement.where(SKU.reserved_quantity > 0)
        elif status_filter == "unavailable":
            statement = statement.where(SKU.is_active.is_(True), on_hand <= SKU.reserved_quantity)
        elif status_filter == "inactive":
            statement = statement.where(SKU.is_active.is_(False))
        if cursor is not None:
            last_product_id, last_sku_id = cursor
            statement = statement.where(
                or_(
                    Product.id > last_product_id,
                    and_(Product.id == last_product_id, SKU.id > last_sku_id),
                )
            )

        result = await self.session.execute(
            statement.order_by(Product.id, SKU.id).limit(limit + 1)
        )
        rows = list(result.mappings().all())
        has_more = len(rows) > limit
        page_rows = rows[:limit]
        next_cursor = None
        if has_more and page_rows:
            next_cursor = (page_rows[-1]["product_id"], page_rows[-1]["sku_id"])
        return {
            "items": [
                {
                    "sku_id": row["sku_id"],
                    "product_id": row["product_id"],
                    "product_title": row["product_title"],
                    "category": row["category"],
                    "status": row["status"],
                    "sku_name": row["sku_name"],
                    "seller_article": row["seller_article"],
                    "stock_quantity": int(row["stock_quantity"]),
                    "reserved_quantity": int(row["reserved_quantity"]),
                    "active_quantity": int(row["stock_quantity"])
                    - int(row["reserved_quantity"]),
                    "is_active": row["is_active"],
                    "revision": row["revision"],
                }
                for row in page_rows
            ],
            "has_more": has_more,
            "next_cursor": next_cursor,
        }

    async def get_dashboard_metrics(self, seller_id: UUID) -> dict[str, object]:
        on_hand = func.coalesce(SKU.on_hand, SKU.stock)
        statement = select(
            func.count(func.distinct(case((and_(Product.deleted.is_(False), Product.is_active.is_(True)), Product.id)))).label("live_products"),
            func.count(SKU.id).label("sku_count"),
            func.coalesce(func.sum(on_hand), 0).label("total_on_hand"),
            func.coalesce(func.sum(on_hand - SKU.reserved_quantity), 0).label("available_stock"),
            func.count(func.distinct(case((Product.status == "ON_MODERATION", Product.id)))).label("pending_moderation"),
            func.coalesce(func.sum(SKU.reserved_quantity), 0).label("reserved_stock"),
            func.now().label("as_of"),
        ).select_from(Product).outerjoin(SKU, SKU.product_id == Product.id).where(
            Product.seller_id == seller_id,
            Product.deleted.is_(False),
        )
        row = (await self.session.execute(statement)).mappings().one()
        return {
            "as_of": row["as_of"],
            "metrics": {
                "live_products": int(row["live_products"]),
                "sku_count": int(row["sku_count"]),
                "total_on_hand": int(row["total_on_hand"]),
                "available_stock": int(row["available_stock"]),
                "pending_moderation": int(row["pending_moderation"]),
                "reserved_stock": int(row["reserved_stock"]),
            },
            "definitions": {
                "live_products": "Seller-owned products not deleted and marked active.",
                "sku_count": "SKUs attached to seller-owned products not marked deleted.",
                "total_on_hand": "Sum of on-hand quantity across those SKUs.",
                "available_stock": "Sum of on-hand minus reserved quantity across those SKUs.",
                "pending_moderation": "Distinct products with status ON_MODERATION.",
                "reserved_stock": "Sum of reserved quantity across those SKUs.",
            },
        }
