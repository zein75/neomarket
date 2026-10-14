from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_current_user, get_db
from src.models.user import User
from src.repositories.address_repo import AddressRepository
from src.schemas.user import AddressInput, AddressResponse


router = APIRouter(tags=["account"])


@router.get("/api/v1/addresses", response_model=list[AddressResponse])
async def list_addresses(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[AddressResponse]:
    addresses = await AddressRepository(db).list_for_user(current_user.id)
    return [AddressResponse.model_validate(address) for address in addresses]


@router.post("/api/v1/addresses", response_model=AddressResponse, status_code=201)
async def create_address(
    data: AddressInput,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AddressResponse:
    address = await AddressRepository(db).create_for_user(
        current_user.id, label=data.label, address_line=data.address_line
    )
    await db.commit()
    await db.refresh(address)
    return AddressResponse.model_validate(address)


@router.delete("/api/v1/addresses/{address_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_address(
    address_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    deleted = await AddressRepository(db).delete_for_user(address_id, current_user.id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "ADDRESS_NOT_FOUND", "message": "Address not found"},
        )
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
