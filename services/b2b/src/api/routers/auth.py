from fastapi import APIRouter, Depends
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_current_seller, get_db
from src.models.seller import Seller
from src.schemas.seller import SellerCreate, SellerResponse, TokenResponse
from src.services.auth_service import AuthService

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=SellerResponse, status_code=201)
async def register(
    data: SellerCreate,
    db: AsyncSession = Depends(get_db),
) -> Seller:
    svc = AuthService(db)
    seller = await svc.register(data)
    await db.commit()
    await db.refresh(seller)
    return seller


@router.post("/login", response_model=TokenResponse)
async def login(
    form: OAuth2PasswordRequestForm = Depends(),
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    svc = AuthService(db)
    seller = await svc.authenticate(form.username, form.password)
    return svc.create_token(seller)


@router.get("/me", response_model=SellerResponse)
async def me(current_seller: Seller = Depends(get_current_seller)) -> Seller:
    return current_seller
