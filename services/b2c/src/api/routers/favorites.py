from uuid import UUID

from fastapi import APIRouter, Depends, Response
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_current_user, get_db
from src.models.user import User
from src.schemas.favorite import (
    FavoriteAdd,
    FavoriteResponse,
    ProductSubscriptionRequest,
    ProductSubscriptionResponse,
)
from src.services.favorite_service import FavoriteService

router = APIRouter(tags=["favorites"])


@router.get("/api/v1/favorites", response_model=list[FavoriteResponse])
@router.get("/favorites", response_model=list[FavoriteResponse], include_in_schema=False)
async def list_favorites(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[FavoriteResponse]:
    return await FavoriteService(db).list_favorites(current_user.id)


@router.post("/api/v1/favorites", response_model=FavoriteResponse, status_code=201)
@router.post(
    "/favorites",
    response_model=FavoriteResponse,
    status_code=201,
    include_in_schema=False,
)
async def add_favorite(
    data: FavoriteAdd,
    response: Response,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> FavoriteResponse:
    svc = FavoriteService(db)
    fav, created = await svc.add_favorite(current_user.id, data)
    await db.commit()
    if created:
        await db.refresh(fav)
    else:
        response.status_code = 200
    return fav


@router.delete("/api/v1/favorites/{product_id}", status_code=204)
@router.delete("/favorites/{product_id}", status_code=204, include_in_schema=False)
async def remove_favorite(
    product_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    svc = FavoriteService(db)
    await svc.remove_favorite(current_user.id, product_id)
    await db.commit()


@router.post(
    "/api/v1/favorites/{product_id}/subscribe",
    response_model=ProductSubscriptionResponse,
    status_code=201,
)
@router.post(
    "/favorites/{product_id}/subscribe",
    response_model=ProductSubscriptionResponse,
    status_code=201,
    include_in_schema=False,
)
async def subscribe_to_product(
    product_id: UUID,
    data: ProductSubscriptionRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ProductSubscriptionResponse:
    subscription = await FavoriteService(db).subscribe(
        current_user.id,
        product_id,
        data,
    )
    await db.commit()
    await db.refresh(subscription)
    return subscription


@router.delete("/api/v1/favorites/{product_id}/subscribe", status_code=204)
@router.delete(
    "/favorites/{product_id}/subscribe",
    status_code=204,
    include_in_schema=False,
)
async def unsubscribe_from_product(
    product_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    await FavoriteService(db).unsubscribe(current_user.id, product_id)
    await db.commit()
