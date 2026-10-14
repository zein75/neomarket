from uuid import UUID

from fastapi import APIRouter, Depends, Header, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_current_user, get_db
from src.models.user import User
from src.schemas.user import (
    LoginRequest,
    ResetConfirm,
    ResetRequest,
    RefreshRequest,
    TokenResponse,
    UserCreate,
    UserResponse,
)
from src.services.auth_service import AuthService
from src.services.cart_service import CartService

router = APIRouter(tags=["auth"])


@router.post("/auth/register", response_model=UserResponse, status_code=201)
@router.post("/api/v1/auth/register", response_model=UserResponse, status_code=201)
async def register(
    data: UserCreate,
    db: AsyncSession = Depends(get_db),
) -> User:
    svc = AuthService(db)
    user = await svc.register(data)
    await db.commit()
    await db.refresh(user)
    return user


@router.post("/auth/login", response_model=TokenResponse)
@router.post("/api/v1/auth/login", response_model=TokenResponse)
async def login(
    data: LoginRequest,
    x_session_id: UUID | None = Header(default=None),
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    svc = AuthService(db)
    user = await svc.authenticate(data.email, data.password)
    if x_session_id:
        await CartService(db).merge_guest_cart(user, str(x_session_id))
        await db.commit()
    token = svc.create_token(user)
    issue_refresh = getattr(svc, "issue_refresh_token", None)
    if issue_refresh is not None:
        token.refresh_token = await issue_refresh(user)
    return token


@router.get("/auth/me", response_model=UserResponse)
@router.get("/api/v1/auth/me", response_model=UserResponse)
async def me(current_user: User = Depends(get_current_user)) -> User:
    return current_user


@router.post("/api/v1/auth/refresh", response_model=TokenResponse)
async def refresh_token(
    data: RefreshRequest,
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    token = await AuthService(db).rotate_refresh_token(data.refresh_token)
    await db.commit()
    return token


@router.post("/api/v1/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    await AuthService(db).revoke_sessions(current_user.id)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/api/v1/auth/reset-request", status_code=status.HTTP_202_ACCEPTED)
async def request_password_reset(
    data: ResetRequest,
    db: AsyncSession = Depends(get_db),
) -> Response:
    # Deliberately identical response for unknown and known accounts.
    await AuthService(db).request_password_reset(str(data.email))
    await db.commit()
    return Response(status_code=status.HTTP_202_ACCEPTED)


@router.post("/api/v1/auth/reset-confirm", status_code=status.HTTP_204_NO_CONTENT)
async def confirm_password_reset(
    data: ResetConfirm,
    db: AsyncSession = Depends(get_db),
) -> Response:
    await AuthService(db).confirm_password_reset(data.reset_token, data.new_password)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
