from fastapi import APIRouter, Depends

from src.api.deps import get_current_seller
from src.models.seller import Seller
from src.schemas.seller import SellerResponse

router = APIRouter(prefix="/sellers", tags=["sellers"])


@router.get("/me", response_model=SellerResponse)
async def get_my_profile(current_seller: Seller = Depends(get_current_seller)) -> Seller:
    return current_seller
