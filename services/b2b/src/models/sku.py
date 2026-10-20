import uuid
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, Boolean, CheckConstraint, ForeignKey, Index, Integer, JSON, String, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import mapped_column, Mapped, relationship

from .base import Base, TimestampMixin

if TYPE_CHECKING:
    from .product import Product


class SKU(Base, TimestampMixin):
    __tablename__ = "skus"
    __table_args__ = (
        CheckConstraint("price >= 0", name="ck_skus_price_nonnegative"),
        CheckConstraint("stock >= 0", name="ck_skus_stock_nonnegative"),
        CheckConstraint(
            "reserved_quantity >= 0", name="ck_skus_reserved_nonnegative"
        ),
        CheckConstraint(
            "reserved_quantity <= COALESCE(on_hand, stock)",
            name="ck_skus_reserved_lte_on_hand",
        ),
        # Kept for compatibility with the original schema during the
        # expand/contract rollout; the runtime invariant is also enforced
        # against on_hand above.
        CheckConstraint(
            "reserved_quantity <= stock", name="ck_skus_reserved_lte_stock"
        ),
        Index("ix_skus_product_id_id", "product_id", "id"),
        Index(
            "ix_skus_catalog_stock",
            "product_id",
            "is_active",
            "on_hand",
            "reserved_quantity",
            "price",
        ),
        Index(
            "uq_skus_product_seller_article_ci",
            "product_id",
            text("lower(seller_article)"),
            unique=True,
            postgresql_where=text("seller_article IS NOT NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    product_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("products.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    price: Mapped[int] = mapped_column(BigInteger, nullable=False)
    stock: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    # Expand/contract migration: kept nullable until all historical rows are
    # backfilled; application code still reads ``stock`` during the rollout.
    on_hand: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    reserved_quantity: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    images: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    seller_article: Mapped[str | None] = mapped_column(String(128), nullable=True)
    currency: Mapped[str] = mapped_column(String(3), default="RUB", nullable=False)
    options: Mapped[dict[str, str]] = mapped_column(JSON, default=dict, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    revision: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    product: Mapped["Product"] = relationship("Product", back_populates="skus")
