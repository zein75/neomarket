import hashlib

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import settings
from src.models.local_carrier_label import LocalCarrierLabel
from src.models.seller_carrier_operation import SellerCarrierOperation
from src.models.seller_shipment import SellerShipment


class LocalCarrierSimulator:
    """Development-only durable label adapter; it never calls an external carrier."""

    async def create_label(
        self,
        session: AsyncSession,
        *,
        operation: SellerCarrierOperation,
        shipment: SellerShipment,
    ) -> LocalCarrierLabel:
        if settings.app_env.lower() not in {"local", "dev", "development", "test"}:
            raise RuntimeError("Local carrier simulation is disabled in production")

        existing = await session.scalar(
            select(LocalCarrierLabel).where(
                LocalCarrierLabel.operation_ref == operation.provider_operation_ref
            )
        )
        if existing is not None:
            return existing

        tracking_suffix = hashlib.sha256(operation.provider_operation_ref.encode()).hexdigest()[:16].upper()
        label = LocalCarrierLabel(
            shipment_id=shipment.id,
            operation_ref=operation.provider_operation_ref,
            tracking_number=f"SIM-{tracking_suffix}",
        )
        session.add(label)
        try:
            await session.commit()
            return label
        except IntegrityError:
            await session.rollback()
            existing = await session.scalar(
                select(LocalCarrierLabel).where(
                    LocalCarrierLabel.operation_ref == operation.provider_operation_ref
                )
            )
            if existing is None:
                raise
            return existing
