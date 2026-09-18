from fastapi import APIRouter, Depends, Header
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_current_user, get_db
from src.models.user import User
from src.schemas.user import TokenResponse, UserCreate, UserResponse
from src.services.auth_service import AuthService
from src.services.cart_service import CartService

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=UserResponse, status_code=201)
async def register(
    data: UserCreate,
    db: AsyncSession = Depends(get_db),
) -> User:
    svc = AuthService(db)
    user = await svc.register(data)
    await db.commit()
    await db.refresh(user)
    return user


@router.post("/login", response_model=TokenResponse)
async def login(
    form: OAuth2PasswordRequestForm = Depends(),
    x_session_id: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    svc = AuthService(db)
    user = await svc.authenticate(form.username, form.password)
    if x_session_id:
        await CartService(db).merge_guest_cart(user, x_session_id)
        await db.commit()
    return svc.create_token(user)


@router.get("/me", response_model=UserResponse)
async def me(current_user: User = Depends(get_current_user)) -> User:
    return current_user
