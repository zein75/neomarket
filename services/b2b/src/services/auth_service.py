import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import settings
from src.core.identity import SellerPrincipal
from src.core.security import create_access_token, hash_password, verify_password
from src.models.seller import Seller
from src.models.seller_invite import SellerInvite
from src.models.seller_session import SellerSession
from src.repositories.seller_repo import SellerRepository
from src.schemas.seller import SellerCreate, TokenResponse


class AuthService:
    def __init__(self, session: AsyncSession) -> None:
        self.repo = SellerRepository(session)

    async def register(self, data: SellerCreate) -> tuple[Seller, str]:
        email = str(data.email).strip().lower()
        existing = await self.repo.get_by_email(email)
        if existing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Email already registered",
            )
        password_hash = hash_password(data.password)
        try:
            seller = await self.repo.create(
                email=email,
                hashed_password=password_hash,
                company_name=data.company_name,
                is_active=False,
                account_status="PENDING_EMAIL",
                email_verified_at=None,
            )
            await self.repo.create_user(
                user_id=seller.id,
                email=email,
                hashed_password=password_hash,
                is_active=True,
            )
            await self.repo.create_membership(
                seller_id=seller.id,
                user_id=seller.id,
                role="OWNER",
            )
        except IntegrityError as exc:
            await self.repo.session.rollback()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Email already registered",
            ) from exc
        token = secrets.token_urlsafe(32)
        await self.repo.create_email_verification(
            seller.id,
            hashlib.sha256(token.encode()).hexdigest(),
            datetime.now(timezone.utc) + timedelta(minutes=30),
        )
        return seller, token

    async def authenticate(
        self, email: str, password: str, organization_id: UUID | None = None
    ) -> SellerPrincipal:
        user = await self.repo.get_user_by_email(email.strip().lower())
        if not user or not verify_password(password, user.hashed_password):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Incorrect email or password",
            )
        if not user.is_active:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account is inactive")
        memberships = await self.repo.list_active_memberships(user.id)
        if organization_id is not None:
            memberships = [
                membership
                for membership in memberships
                if membership.seller_id == organization_id
            ]
        if not memberships:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No active seller organization membership",
            )
        if len(memberships) > 1:
            organizations = []
            for membership in memberships:
                organization = await self.repo.get_by_id(membership.seller_id)
                if (
                    organization
                    and organization.is_active
                    and organization.account_status == "ACTIVE"
                ):
                    organizations.append(
                        {
                            "id": str(organization.id),
                            "company_name": organization.company_name,
                            "role": membership.role,
                        }
                    )
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "ORGANIZATION_SELECTION_REQUIRED",
                    "message": "Choose an organization where you have an active membership",
                    "organizations": organizations,
                },
            )
        membership = memberships[0]
        seller = await self.repo.get_by_id(membership.seller_id)
        if seller is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid seller membership")
        if seller.account_status == "PENDING_EMAIL" or user.email_verified_at is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Email verification required",
            )
        if seller.account_status == "PENDING_REVIEW":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Account is awaiting review",
            )
        if not seller.is_active or seller.account_status != "ACTIVE":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Account is inactive",
            )
        return SellerPrincipal(seller, user, membership)

    async def verify_email(self, token: str) -> str:
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        challenge = await self.repo.get_email_verification_by_hash(token_hash)
        now = datetime.now(timezone.utc)
        if not challenge or challenge.consumed_at is not None or challenge.expires_at <= now:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Verification link is invalid or expired",
            )
        seller = await self.repo.get_by_id(challenge.seller_id)
        if not seller or seller.account_status != "PENDING_EMAIL":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Verification link is invalid or expired",
            )
        if not await self.repo.consume_email_verification(challenge.id, now):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Verification link is invalid or expired",
            )
        seller.email_verified_at = now
        seller.account_status = "PENDING_REVIEW"
        seller.is_active = False
        user = await self.repo.get_user_by_id(seller.id)
        if user is not None:
            user.email_verified_at = now
        await self.repo.session.flush()
        return seller.account_status

    async def issue_email_verification(self, email: str) -> tuple[str, str] | None:
        seller = await self.repo.get_by_email(email.strip().lower())
        if not seller or seller.account_status != "PENDING_EMAIL":
            return None
        token = secrets.token_urlsafe(32)
        await self.repo.create_email_verification(
            seller.id,
            hashlib.sha256(token.encode()).hexdigest(),
            datetime.now(timezone.utc) + timedelta(minutes=30),
        )
        return seller.email, token

    @staticmethod
    def _invite_email_hash(email: str) -> str:
        return hmac.new(
            settings.secret_key.encode(),
            email.strip().lower().encode(),
            hashlib.sha256,
        ).hexdigest()

    async def issue_seller_invite(
        self,
        *,
        seller_id: UUID,
        invited_by_user_id: UUID,
        email: str,
        role: str,
    ) -> tuple[SellerInvite, str]:
        normalized_email = email.strip().lower()
        user = await self.repo.get_user_by_email(normalized_email)
        if user:
            membership = await self.repo.get_membership(
                seller_id, user.id, active_only=False
            )
            if membership and membership.active:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="User is already a member of this seller organization",
                )
        now = datetime.now(timezone.utc)
        email_hash = self._invite_email_hash(normalized_email)
        await self.repo.revoke_pending_invites(seller_id, email_hash, now)
        token = secrets.token_urlsafe(32)
        invite = await self.repo.create_invite(
            seller_id=seller_id,
            invited_by_user_id=invited_by_user_id,
            recipient_email_hash=email_hash,
            role=role,
            token_hash=hashlib.sha256(token.encode()).hexdigest(),
            expires_at=now + timedelta(hours=settings.seller_invitation_ttl_hours),
        )
        return invite, token

    async def accept_seller_invite(
        self, *, token: str, email: str, password: str
    ) -> tuple[str, UUID, str]:
        normalized_email = email.strip().lower()
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        invite = await self.repo.get_invite_by_token_hash(token_hash)
        now = datetime.now(timezone.utc)
        if (
            not invite
            or invite.accepted_at is not None
            or invite.revoked_at is not None
            or invite.expires_at <= now
            or not hmac.compare_digest(
                invite.recipient_email_hash,
                self._invite_email_hash(normalized_email),
            )
        ):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invitation is invalid, expired, or already used",
            )
        organization = await self.repo.get_by_id(invite.seller_id)
        if not organization or not organization.is_active or organization.account_status != "ACTIVE":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Seller organization is not active",
            )
        if not await self.repo.consume_invite(invite.id, now):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invitation is invalid, expired, or already used",
            )

        user = await self.repo.get_user_by_email(normalized_email)
        if user:
            if not user.is_active or not verify_password(password, user.hashed_password):
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Email or password is incorrect",
                )
            if user.email_verified_at is None:
                user.email_verified_at = now
        else:
            user = await self.repo.create_user(
                user_id=uuid4(),
                email=normalized_email,
                hashed_password=hash_password(password),
                is_active=True,
                email_verified_at=now,
            )

        membership = await self.repo.get_membership(
            organization.id, user.id, active_only=False
        )
        if membership:
            if membership.active:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="User is already a member of this seller organization",
                )
            membership.active = True
            membership.role = invite.role
            user.session_version += 1
        else:
            await self.repo.create_membership(
                seller_id=organization.id,
                user_id=user.id,
                role=invite.role,
            )
        return normalized_email, organization.id, invite.role

    def create_token(self, seller: Seller | SellerPrincipal) -> TokenResponse:
        if isinstance(seller, SellerPrincipal):
            return TokenResponse(
                access_token=create_access_token(
                    str(seller.user_id),
                    seller.session_version,
                    seller_id=str(seller.id),
                ),
                expires_in=settings.access_token_expire_minutes * 60,
            )
        return TokenResponse(
            access_token=create_access_token(str(seller.id), seller.session_version),
            expires_in=settings.access_token_expire_minutes * 60,
        )

    async def create_opaque_session(
        self,
        seller: Seller | SellerPrincipal,
        *,
        device_label: str | None = None,
        user_agent: str | None = None,
        ip_address: str | None = None,
        refresh_family_id: UUID | None = None,
    ) -> TokenResponse:
        """Issue a short-lived opaque session for the Next BFF.

        Only a SHA-256 digest is persisted.  JWT login remains available for
        direct service clients, while browser traffic can exchange it once and
        use a revocable server-side session thereafter.
        """
        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(minutes=settings.access_token_expire_minutes)
        refresh_expires_at = now + timedelta(days=30)
        raw_token = secrets.token_urlsafe(48)
        principal = seller if isinstance(seller, SellerPrincipal) else None
        user_id = principal.user_id if principal else seller.id
        seller_id = principal.id if principal else seller.id
        user_session_version = principal.user.session_version if principal else seller.session_version
        seller_session_version = principal.organization.session_version if principal else seller.session_version
        session = SellerSession(
            token_hash=hashlib.sha256(raw_token.encode()).hexdigest(),
            user_id=user_id,
            seller_id=seller_id,
            user_session_version=user_session_version,
            seller_session_version=seller_session_version,
            refresh_family_id=refresh_family_id or uuid4(),
            expires_at=expires_at,
            refresh_expires_at=refresh_expires_at,
            last_seen_at=now,
            device_label=device_label[:160] if device_label else None,
            user_agent=user_agent[:512] if user_agent else None,
            ip_address=ip_address[:64] if ip_address else None,
        )
        self.repo.session.add(session)
        await self.repo.session.flush()
        return TokenResponse(
            access_token=raw_token,
            expires_in=max(1, int((expires_at - now).total_seconds())),
        )
