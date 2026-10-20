from datetime import datetime, timezone

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID

from src.models.seller import Seller
from src.models.seller_email_verification import SellerEmailVerification
from src.models.seller_membership import SellerMembership
from src.models.seller_invite import SellerInvite
from src.models.seller_user import SellerUser
from src.models.seller_session import SellerSession
from .base import BaseRepository


class SellerRepository(BaseRepository[Seller]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Seller)

    async def get_by_email(self, email: str) -> Seller | None:
        result = await self.session.execute(
            select(Seller).where(func.lower(Seller.email) == email.strip().lower())
        )
        return result.scalar_one_or_none()

    async def get_user_by_id(self, user_id: UUID) -> SellerUser | None:
        return await self.session.get(SellerUser, user_id)

    async def get_user_by_email(self, email: str) -> SellerUser | None:
        result = await self.session.execute(
            select(SellerUser).where(func.lower(SellerUser.email) == email.strip().lower())
        )
        return result.scalar_one_or_none()

    async def get_membership(
        self, seller_id: UUID, user_id: UUID, *, active_only: bool = True
    ) -> SellerMembership | None:
        query = select(SellerMembership).where(
            SellerMembership.seller_id == seller_id,
            SellerMembership.user_id == user_id,
        )
        if active_only:
            query = query.where(SellerMembership.active.is_(True))
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def get_membership_for_update(
        self, seller_id: UUID, user_id: UUID
    ) -> SellerMembership | None:
        result = await self.session.execute(
            select(SellerMembership)
            .where(
                SellerMembership.seller_id == seller_id,
                SellerMembership.user_id == user_id,
                SellerMembership.active.is_(True),
            )
            .with_for_update()
        )
        return result.scalar_one_or_none()

    async def list_active_memberships(self, user_id: UUID) -> list[SellerMembership]:
        result = await self.session.execute(
            select(SellerMembership).where(
                SellerMembership.user_id == user_id,
                SellerMembership.active.is_(True),
            )
        )
        return list(result.scalars().all())

    async def list_members(self, seller_id: UUID) -> list[tuple[SellerMembership, SellerUser]]:
        result = await self.session.execute(
            select(SellerMembership, SellerUser)
            .join(SellerUser, SellerUser.id == SellerMembership.user_id)
            .where(SellerMembership.seller_id == seller_id)
            .order_by(SellerMembership.created_at, SellerMembership.id)
        )
        return list(result.all())

    async def create_user(
        self,
        *,
        user_id: UUID,
        email: str,
        hashed_password: str,
        is_active: bool = True,
        email_verified_at: datetime | None = None,
    ) -> SellerUser:
        user = SellerUser(
            id=user_id,
            email=email,
            hashed_password=hashed_password,
            is_active=is_active,
            email_verified_at=email_verified_at,
        )
        self.session.add(user)
        await self.session.flush()
        return user

    async def create_membership(
        self, *, seller_id: UUID, user_id: UUID, role: str, active: bool = True
    ) -> SellerMembership:
        membership = SellerMembership(
            seller_id=seller_id,
            user_id=user_id,
            role=role,
            active=active,
        )
        self.session.add(membership)
        await self.session.flush()
        return membership

    async def revoke_pending_invites(
        self, seller_id: UUID, recipient_email_hash: str, now: datetime
    ) -> None:
        await self.session.execute(
            update(SellerInvite)
            .where(
                SellerInvite.seller_id == seller_id,
                SellerInvite.recipient_email_hash == recipient_email_hash,
                SellerInvite.accepted_at.is_(None),
                SellerInvite.revoked_at.is_(None),
            )
            .values(revoked_at=now)
        )

    async def create_invite(
        self,
        *,
        seller_id: UUID,
        invited_by_user_id: UUID,
        recipient_email_hash: str,
        role: str,
        token_hash: str,
        expires_at: datetime,
    ) -> SellerInvite:
        invite = SellerInvite(
            seller_id=seller_id,
            invited_by_user_id=invited_by_user_id,
            recipient_email_hash=recipient_email_hash,
            role=role,
            token_hash=token_hash,
            expires_at=expires_at,
        )
        self.session.add(invite)
        await self.session.flush()
        return invite

    async def get_invite_by_token_hash(self, token_hash: str) -> SellerInvite | None:
        result = await self.session.execute(
            select(SellerInvite).where(SellerInvite.token_hash == token_hash)
        )
        return result.scalar_one_or_none()

    async def consume_invite(self, invite_id: UUID, now: datetime) -> bool:
        result = await self.session.execute(
            update(SellerInvite)
            .where(
                SellerInvite.id == invite_id,
                SellerInvite.accepted_at.is_(None),
                SellerInvite.revoked_at.is_(None),
                SellerInvite.expires_at > now,
            )
            .values(accepted_at=now)
            .returning(SellerInvite.id)
        )
        return result.scalar_one_or_none() is not None

    async def revoke_all_sessions(self, seller_id: UUID) -> bool:
        result = await self.session.execute(
            update(Seller)
            .where(Seller.id == seller_id)
            .values(session_version=Seller.session_version + 1)
            .execution_options(synchronize_session=False)
        )
        if result.rowcount == 1:
            await self.session.execute(
                update(SellerSession)
                .where(
                    SellerSession.seller_id == seller_id,
                    SellerSession.revoked_at.is_(None),
                )
                .values(revoked_at=datetime.now(timezone.utc))
            )
        return result.rowcount == 1

    async def revoke_user_sessions(self, user_id: UUID) -> bool:
        result = await self.session.execute(
            update(SellerUser)
            .where(SellerUser.id == user_id)
            .values(session_version=SellerUser.session_version + 1)
            .execution_options(synchronize_session=False)
        )
        if result.rowcount == 1:
            await self.session.execute(
                update(SellerSession)
                .where(
                    SellerSession.user_id == user_id,
                    SellerSession.revoked_at.is_(None),
                )
                .values(revoked_at=datetime.now(timezone.utc))
            )
        return result.rowcount == 1

    async def suspend(self, seller_id: UUID) -> bool:
        result = await self.session.execute(
            update(Seller)
            .where(Seller.id == seller_id)
            .values(
                is_active=False,
                account_status="SUSPENDED",
                session_version=Seller.session_version + 1,
            )
            .execution_options(synchronize_session=False)
        )
        if result.rowcount != 1:
            return False
        await self.session.execute(
            update(SellerUser)
            .where(
                SellerUser.id.in_(
                    select(SellerMembership.user_id).where(
                        SellerMembership.seller_id == seller_id
                    )
                )
            )
            .values(session_version=SellerUser.session_version + 1)
            .execution_options(synchronize_session=False)
        )
        return True

    async def create_email_verification(
        self, seller_id: UUID, token_hash: str, expires_at: datetime
    ) -> SellerEmailVerification:
        now = datetime.now(expires_at.tzinfo)
        await self.session.execute(
            update(SellerEmailVerification)
            .where(
                SellerEmailVerification.seller_id == seller_id,
                SellerEmailVerification.consumed_at.is_(None),
            )
            .values(consumed_at=now)
        )
        challenge = SellerEmailVerification(
            seller_id=seller_id,
            token_hash=token_hash,
            expires_at=expires_at,
        )
        self.session.add(challenge)
        await self.session.flush()
        return challenge

    async def get_email_verification_by_hash(
        self, token_hash: str
    ) -> SellerEmailVerification | None:
        result = await self.session.execute(
            select(SellerEmailVerification).where(
                SellerEmailVerification.token_hash == token_hash
            )
        )
        return result.scalar_one_or_none()

    async def consume_email_verification(self, challenge_id: UUID, now: datetime) -> bool:
        result = await self.session.execute(
            update(SellerEmailVerification)
            .where(
                SellerEmailVerification.id == challenge_id,
                SellerEmailVerification.consumed_at.is_(None),
                SellerEmailVerification.expires_at > now,
            )
            .values(consumed_at=now)
            .returning(SellerEmailVerification.id)
        )
        return result.scalar_one_or_none() is not None
