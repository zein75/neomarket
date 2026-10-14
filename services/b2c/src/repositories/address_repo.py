from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.address import Address


class AddressRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_for_user(self, address_id: UUID, user_id: UUID) -> Address | None:
        result = await self.session.execute(
            select(Address).where(Address.id == address_id, Address.user_id == user_id)
        )
        return result.scalar_one_or_none()

    async def list_for_user(self, user_id: UUID) -> list[Address]:
        result = await self.session.execute(
            select(Address)
            .where(Address.user_id == user_id)
            .order_by(Address.is_default.desc(), Address.created_at.desc())
        )
        return list(result.scalars().all())

    async def create_for_user(
        self, user_id: UUID, *, label: str, address_line: str
    ) -> Address:
        address = Address(
            user_id=user_id,
            label=label,
            address_line=address_line,
            country="RU",
            city=label,
            street=address_line,
            building="-",
        )
        self.session.add(address)
        await self.session.flush()
        return address

    async def delete_for_user(self, address_id: UUID, user_id: UUID) -> bool:
        address = await self.get_for_user(address_id, user_id)
        if address is None:
            return False
        await self.session.delete(address)
        await self.session.flush()
        return True
