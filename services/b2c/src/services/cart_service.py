from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.clients.b2b_client import B2BClient
from src.core.config import settings
from src.models.cart import Cart, CartItem
from src.models.user import User
from src.repositories.cart_repo import CartRepository
from src.schemas.cart import CartItemAdd, CartItemUpdate


class CartService:
    def __init__(self, session: AsyncSession) -> None:
        self.repo = CartRepository(session)

    async def get_or_create_cart(
        self,
        user: User | None = None,
        session_id: str | None = None,
    ) -> Cart:
        if user:
            cart = await self.repo.get_by_user_id(user.id)
            if not cart:
                cart = await self.repo.create(user_id=user.id)
            if session_id:
                guest_cart = await self.repo.get_by_session_id(session_id)
                if guest_cart and guest_cart.id != cart.id:
                    await self._merge_guest_cart(cart, guest_cart)
        elif session_id:
            cart = await self.repo.get_by_session_id(session_id)
            if not cart:
                cart = await self.repo.create(session_id=session_id)
        else:
            cart = await self.repo.create()
        return cart

    async def _merge_guest_cart(self, auth_cart: Cart, guest_cart: Cart) -> None:
        auth_by_sku = {item.sku_id: item for item in auth_cart.items}
        for guest_item in list(guest_cart.items):
            auth_item = auth_by_sku.get(guest_item.sku_id)
            if auth_item:
                await self.repo.update_item_quantity(
                    auth_item,
                    max(auth_item.quantity, guest_item.quantity),
                )
            else:
                await self.repo.add_item(
                    cart_id=auth_cart.id,
                    sku_id=guest_item.sku_id,
                    product_id=guest_item.product_id,
                    quantity=guest_item.quantity,
                    unit_price=getattr(guest_item, "unit_price", 0),
                )
        await self.repo.remove_cart(guest_cart)

    async def get_cart_with_items(self, cart_id: UUID) -> Cart:
        cart = await self.repo.get_with_items(cart_id)
        if not cart:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Cart not found"
            )
        return cart

    async def add_item(self, cart_id: UUID, data: CartItemAdd) -> CartItem:
        cart = await self.repo.get_with_items(cart_id)
        if not cart:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Cart not found"
            )
        for item in cart.items:
            if item.sku_id == data.sku_id:
                return await self.repo.update_item_quantity(
                    item, item.quantity + data.quantity
                )

        product_id = data.product_id
        unit_price = data.unit_price or 0
        if product_id is None:
            sku_data = await self._get_sku_data(data.sku_id)
            product_id = UUID(str(sku_data["product_id"]))
            unit_price = int(sku_data.get("price") or unit_price)
        return await self.repo.add_item(
            cart_id=cart_id,
            sku_id=data.sku_id,
            product_id=product_id,
            quantity=data.quantity,
            unit_price=unit_price,
        )

    async def update_item(
        self,
        item_id: UUID,
        data: CartItemUpdate,
        cart_id: UUID | None = None,
    ) -> CartItem:
        item = await self.repo.get_item(item_id)
        if not item or (cart_id is not None and item.cart_id != cart_id):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Cart item not found"
            )
        return await self.repo.update_item_quantity(item, data.quantity)

    async def remove_item(self, item_id: UUID, cart_id: UUID | None = None) -> None:
        item = await self.repo.get_item(item_id)
        if not item or (cart_id is not None and item.cart_id != cart_id):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Cart item not found"
            )
        await self.repo.remove_item(item)

    async def get_enriched_cart(self, cart_id: UUID) -> dict[str, object]:
        cart = await self.get_cart_with_items(cart_id)
        product_ids = sorted({str(item.product_id) for item in cart.items})
        products = await self._get_products(product_ids)
        product_by_id = {str(product.get("id")): product for product in products}
        sku_index = self._build_sku_index(products)

        response_items: list[dict[str, object]] = []
        subtotal = 0
        is_valid = True
        for item in cart.items:
            product = product_by_id.get(str(item.product_id))
            sku_entry = sku_index.get(str(item.sku_id))
            enriched = self._enrich_item(item, product, sku_entry)
            if enriched["is_available"]:
                subtotal += int(enriched["line_total"])
            else:
                is_valid = False
            response_items.append(enriched)

        return {
            "id": cart.id,
            "user_id": cart.user_id,
            "session_id": cart.session_id,
            "currency": cart.currency,
            "items": response_items,
            "items_count": sum(item.quantity for item in cart.items),
            "subtotal": subtotal,
            "is_valid": is_valid,
        }

    async def _get_products(self, product_ids: list[str]) -> list[dict[str, object]]:
        if not product_ids:
            return []
        async with B2BClient(settings.b2b_base_url) as client:
            return await client.get_products_batch(product_ids)

    async def _get_sku_data(self, sku_id: UUID) -> dict[str, object]:
        async with B2BClient(settings.b2b_base_url) as client:
            return await client.get_sku(str(sku_id))

    def _build_sku_index(
        self,
        products: list[dict[str, object]],
    ) -> dict[str, tuple[dict[str, object], dict[str, object]]]:
        index = {}
        for product in products:
            for sku in product.get("skus", []):
                index[str(sku.get("id"))] = (product, sku)
        return index

    def _enrich_item(
        self,
        item: CartItem,
        product: dict[str, object] | None,
        sku_entry: tuple[dict[str, object], dict[str, object]] | None,
    ) -> dict[str, object]:
        indexed_product, sku = sku_entry if sku_entry else (product, None)
        product = indexed_product or product
        unavailable_reason = self._unavailable_reason(item, product, sku)
        is_available = unavailable_reason is None
        unit_price = int(sku.get("price", 0)) if sku else 0
        name_parts = [
            str(product.get("title", "") if product else "").strip(),
            str(sku.get("name", "") if sku else "").strip(),
        ]
        return {
            "sku_id": item.sku_id,
            "product_id": item.product_id,
            "name": " ".join(part for part in name_parts if part) or "Unavailable SKU",
            "quantity": item.quantity,
            "unit_price": unit_price,
            "unit_price_at_add": getattr(item, "unit_price", None),
            "line_total": item.quantity * unit_price if is_available else 0,
            "available_quantity": int(sku.get("active_quantity", 0)) if sku else 0,
            "is_available": is_available,
            "unavailable_reason": unavailable_reason,
            "image": self._first_image(sku),
        }

    def _unavailable_reason(
        self,
        item: CartItem,
        product: dict[str, object] | None,
        sku: dict[str, object] | None,
    ) -> str | None:
        if not product or not sku:
            return "SKU_NOT_FOUND"
        if product.get("deleted") is True:
            return "PRODUCT_DELETED"
        if product.get("status") in {"BLOCKED", "HARD_BLOCKED"}:
            return "PRODUCT_BLOCKED"
        active_quantity = int(sku.get("active_quantity", 0))
        if active_quantity <= 0:
            return "OUT_OF_STOCK"
        if item.quantity > active_quantity:
            return "INSUFFICIENT_STOCK"
        return None

    def _first_image(self, sku: dict[str, object] | None) -> dict[str, object] | None:
        if not sku:
            return None
        images = sku.get("images") or []
        if not images:
            return None
        first = images[0]
        if isinstance(first, dict):
            return first
        return {"url": first}
