from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_current_user, get_db
from src.models.user import User
from src.schemas.favorite import FavoriteAdd, FavoriteResponse
from src.services.favorite_service import FavoriteService

router = APIRouter(prefix="/favorites", tags=["favorites"])


@router.get("", response_model=list[FavoriteResponse])
async def list_favorites(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[FavoriteResponse]:
    return await FavoriteService(db).list_favorites(current_user.id)


@router.post("", response_model=FavoriteResponse, status_code=201)
async def add_favorite(
    data: FavoriteAdd,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> FavoriteResponse:
    svc = FavoriteService(db)
    fav = await svc.add_favorite(current_user.id, data)
    await db.commit()
    await db.refresh(fav)
    return fav


@router.delete("/{product_id}", status_code=204)
async def remove_favorite(
    product_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    svc = FavoriteService(db)
    await svc.remove_favorite(current_user.id, product_id)
    await db.commit()
