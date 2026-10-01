from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
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
                cart = await self._create_cart_once(user_id=user.id)
        elif session_id:
            cart = await self.repo.get_by_session_id(session_id)
            if not cart:
                cart = await self._create_cart_once(session_id=session_id)
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "code": "MISSING_CART_IDENTITY",
                    "message": "Provide Authorization or X-Session-Id",
                },
            )
        return cart

    async def _create_cart_once(
        self,
        *,
        user_id: UUID | None = None,
        session_id: str | None = None,
    ) -> Cart:
        """Return the cart created by this request or by a concurrent one."""
        try:
            return await self.repo.create(user_id=user_id, session_id=session_id)
        except IntegrityError:
            await self.repo.session.rollback()
            cart = (
                await self.repo.get_by_user_id(user_id)
                if user_id is not None
                else await self.repo.get_by_session_id(session_id or "")
            )
            if cart:
                return cart
            raise

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

    async def merge_guest_cart(self, user: User, session_id: str) -> Cart:
        auth_cart = await self.repo.get_by_user_id(user.id)
        if not auth_cart:
            auth_cart = await self._create_cart_once(user_id=user.id)
        guest_cart = await self.repo.get_by_session_id(session_id)
        if guest_cart and guest_cart.id != auth_cart.id:
            await self._merge_guest_cart(auth_cart, guest_cart)
        return auth_cart

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

        # The cart flow requires the SKU/product availability check before both
        # inserting a new line and increasing an existing one.
        sku_data = await self._get_sku_data(data.sku_id)
        self._ensure_sku_can_be_added(sku_data, data.quantity)

        for item in cart.items:
            if item.sku_id == data.sku_id:
                requested_quantity = item.quantity + data.quantity
                self._ensure_sku_can_be_added(sku_data, requested_quantity)
                return await self.repo.update_item_quantity(
                    item, requested_quantity
                )

        product_id = UUID(str(sku_data["product_id"]))
        unit_price = int(sku_data.get("price") or 0)
        return await self.repo.add_item(
            cart_id=cart_id,
            sku_id=data.sku_id,
            product_id=product_id,
            quantity=data.quantity,
            unit_price=unit_price,
        )

    def _ensure_sku_can_be_added(
        self,
        sku_data: dict[str, object],
        quantity: int,
    ) -> None:
        if not sku_data or not sku_data.get("product_id"):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"code": "SKU_NOT_FOUND", "message": "SKU not found"},
            )

        product_status = str(
            sku_data.get("product_status", sku_data.get("status", "MODERATED"))
        )
        if (
            sku_data.get("deleted") is True
            or sku_data.get("is_active") is False
            or product_status != "MODERATED"
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "PRODUCT_NOT_AVAILABLE",
                    "message": "Product is not available",
                },
            )

        available_quantity = int(sku_data.get("active_quantity", 0))
        if quantity > available_quantity:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "INSUFFICIENT_STOCK",
                    "message": "Requested quantity exceeds available stock",
                },
            )

    async def get_item(self, sku_id: UUID, *, cart_id: UUID) -> CartItem:
        item = await self.repo.get_item_by_sku(cart_id, sku_id)
        if not item:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Cart item not found"
            )
        return item

    async def update_item(
        self,
        sku_id: UUID,
        data: CartItemUpdate,
        cart_id: UUID | None = None,
    ) -> CartItem:
        if cart_id is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Cart item not found"
            )
        item = await self.repo.get_item_by_sku(cart_id, sku_id)
        if not item:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Cart item not found"
            )
        sku_data = await self._get_sku_data(item.sku_id)
        product_status = str(
            sku_data.get("product_status", sku_data.get("status", "MODERATED"))
        )
        if sku_data.get("is_active") is False or product_status != "MODERATED":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "PRODUCT_NOT_AVAILABLE",
                    "message": "Product is not available",
                },
            )
        available_quantity = int(sku_data.get("active_quantity", 0))
        if data.quantity > available_quantity:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "INSUFFICIENT_STOCK",
                    "message": "Requested quantity exceeds available stock",
                },
            )
        return await self.repo.update_item_quantity(item, data.quantity)

    async def remove_item(self, sku_id: UUID, cart_id: UUID | None = None) -> None:
        if cart_id is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Cart item not found"
            )
        item = await self.repo.get_item_by_sku(cart_id, sku_id)
        if not item:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Cart item not found"
            )
        await self.repo.remove_item(item)

    async def clear_cart(self, cart_id: UUID) -> None:
        cart = await self.repo.get_with_items(cart_id)
        if not cart:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Cart not found"
            )
        await self.repo.clear_items(cart)

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
            if (
                not enriched["is_available"]
                or enriched["quantity"] > enriched["available_quantity"]
            ):
                is_valid = False
            response_items.append(enriched)

        return {
            "id": cart.id,
            "items": response_items,
            "items_count": sum(item.quantity for item in cart.items),
            "subtotal": subtotal,
            "is_valid": is_valid,
            "updated_at": getattr(cart, "updated_at", None),
        }

    async def validate_cart(self, cart_id: UUID) -> dict[str, object]:
        cart = await self.get_enriched_cart(cart_id)
        issues = []
        for item in cart["items"]:
            if (
                item.get("unit_price_at_add") is not None
                and item["unit_price_at_add"] != item["unit_price"]
            ):
                issues.append(
                    {
                        "sku_id": item["sku_id"],
                        "type": "PRICE_CHANGED",
                        "message": "Cart item price has changed",
                        "old_value": item["unit_price_at_add"],
                        "new_value": item["unit_price"],
                    }
                )
            reason = item.get("unavailable_reason")
            if reason:
                issue_type = {
                    "PRODUCT_BLOCKED": "PRODUCT_BLOCKED",
                    "PRODUCT_DELISTED": "PRODUCT_DELETED",
                    "ON_MODERATION": "PRODUCT_BLOCKED",
                }.get(str(reason), str(reason))
                issue = {
                    "sku_id": item["sku_id"],
                    "type": issue_type,
                    "message": f"Cart item is not available: {reason}",
                }
                if reason == "INSUFFICIENT_STOCK":
                    issue["old_value"] = item["quantity"]
                    issue["new_value"] = item["available_quantity"]
                issues.append(issue)
            elif item["quantity"] > item["available_quantity"]:
                issues.append(
                    {
                        "sku_id": item["sku_id"],
                        "type": "QUANTITY_REDUCED",
                        "message": "Only part of the requested quantity is available",
                        "old_value": item["quantity"],
                        "new_value": item["available_quantity"],
                    }
                )
        is_valid = not issues
        return {
            "is_valid": is_valid,
            "cart": cart,
            "issues": issues,
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
            return "PRODUCT_DELISTED"
        if product.get("deleted") is True:
            return "PRODUCT_DELISTED"
        if product.get("status") in {"BLOCKED", "HARD_BLOCKED"}:
            return "PRODUCT_BLOCKED"
        if product.get("status") in {"ON_MODERATION", "EDITED"}:
            return "ON_MODERATION"
        active_quantity = int(sku.get("active_quantity", 0))
        if active_quantity <= 0:
            return "OUT_OF_STOCK"
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
