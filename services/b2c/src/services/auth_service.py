import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.security import create_access_token, hash_password, verify_password
from src.core.config import settings
from src.models.password_reset import PasswordResetToken
from src.models.refresh_session import RefreshSession
from src.models.user import User
from src.repositories.user_repo import UserRepository
from src.schemas.user import TokenResponse, UserCreate


class AuthService:
    def __init__(self, session: AsyncSession) -> None:
        self.repo = UserRepository(session)

    async def register(self, data: UserCreate) -> User:
        existing = await self.repo.get_by_email(data.email)
        if existing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Email already registered",
            )
        return await self.repo.create(
            email=data.email,
            hashed_password=hash_password(data.password),
            first_name=data.first_name,
            last_name=data.last_name,
            phone=data.phone,
        )

    async def authenticate(self, email: str, password: str) -> User:
        user = await self.repo.get_by_email(email)
        if not user or not verify_password(password, user.hashed_password):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Incorrect email or password",
            )
        if not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Account is inactive",
            )
        return user

    def create_token(self, user: User) -> TokenResponse:
        return TokenResponse(
            access_token=create_access_token(str(user.id)),
            expires_in=settings.access_token_expire_minutes * 60,
        )

    async def issue_refresh_token(self, user: User) -> str:
        raw_token = secrets.token_urlsafe(48)
        self.repo.session.add(
            RefreshSession(
                user_id=user.id,
                token_hash=hashlib.sha256(raw_token.encode()).hexdigest(),
                expires_at=datetime.now(timezone.utc) + timedelta(days=30),
            )
        )
        await self.repo.session.flush()
        return raw_token

    async def rotate_refresh_token(self, raw_token: str) -> TokenResponse:
        token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
        result = await self.repo.session.execute(
            select(RefreshSession)
            .where(
                RefreshSession.token_hash == token_hash,
                RefreshSession.revoked_at.is_(None),
                RefreshSession.expires_at > datetime.now(timezone.utc),
            )
            .with_for_update()
        )
        session = result.scalar_one_or_none()
        if session is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={"code": "REFRESH_TOKEN_INVALID", "message": "Invalid refresh token"},
            )
        user = await self.repo.get_by_id(session.user_id)
        if user is None or not user.is_active:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token")
        session.revoked_at = datetime.now(timezone.utc)
        new_refresh = await self.issue_refresh_token(user)
        token = self.create_token(user)
        token.refresh_token = new_refresh
        return token

    async def revoke_sessions(self, user_id) -> None:
        await self.repo.session.execute(
            RefreshSession.__table__.update()
            .where(RefreshSession.user_id == user_id, RefreshSession.revoked_at.is_(None))
            .values(revoked_at=datetime.now(timezone.utc))
        )

    async def request_password_reset(self, email: str) -> str | None:
        user = await self.repo.get_by_email(email)
        if user is None or not user.is_active:
            return None
        raw_token = secrets.token_urlsafe(32)
        token = PasswordResetToken(
            user_id=user.id,
            token_hash=hashlib.sha256(raw_token.encode()).hexdigest(),
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=15),
        )
        self.repo.session.add(token)
        await self.repo.session.flush()
        return raw_token

    async def confirm_password_reset(self, raw_token: str, new_password: str) -> None:
        token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
        result = await self.repo.session.execute(
            select(PasswordResetToken)
            .where(
                PasswordResetToken.token_hash == token_hash,
                PasswordResetToken.used_at.is_(None),
                PasswordResetToken.expires_at > datetime.now(timezone.utc),
            )
            .with_for_update()
        )
        token = result.scalar_one_or_none()
        if token is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"code": "RESET_TOKEN_INVALID", "message": "Reset token is expired or already used"},
            )
        user = await self.repo.get_by_id(token.user_id)
        if user is None or not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"code": "RESET_TOKEN_INVALID", "message": "Reset token is expired or already used"},
            )
        user.hashed_password = hash_password(new_password)
        token.used_at = datetime.now(timezone.utc)
        await self.repo.session.flush()
