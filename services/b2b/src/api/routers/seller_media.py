from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from fastapi.responses import FileResponse
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_current_seller, get_db, require_seller_permission
from src.core.config import settings
from src.core.redis import get_redis
from src.models.seller import Seller
from src.models.seller_media_asset import SellerMediaAsset
from src.schemas.seller_media import SellerMediaIntentCreate, SellerMediaIntentResponse, SellerMediaStatusResponse
from src.services.seller_media_service import SellerMediaService
from src.services.media_upload_rate_limiter import check_media_upload_rate_limit

router = APIRouter(tags=["seller-media"])


@router.post("/api/v1/seller/media/uploads", response_model=SellerMediaIntentResponse, status_code=201)
async def create_upload_intent(
    data: SellerMediaIntentCreate,
    idempotency_key: UUID = Header(alias="Idempotency-Key"),
    seller: Seller = Depends(require_seller_permission("catalog.write")),
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
) -> SellerMediaIntentResponse:
    await check_media_upload_rate_limit(redis, seller.id)
    asset, token = await SellerMediaService(db).create_intent(seller.id, data, str(idempotency_key))
    await db.commit()
    return SellerMediaIntentResponse(id=asset.id, upload_url=f"/api/v1/media/uploads/{asset.id}?token={token}", expires_at=asset.upload_expires_at.isoformat(), state=asset.state)


@router.put("/api/v1/media/uploads/{asset_id}", status_code=204)
async def upload_bytes(asset_id: UUID, request: Request, token: str, db: AsyncSession = Depends(get_db)) -> Response:
    content_length = request.headers.get("content-length")
    if content_length and (not content_length.isdigit() or int(content_length) > 10_000_000):
        raise HTTPException(413, detail={"code": "MEDIA_TOO_LARGE", "message": "Image exceeds the 10 MB limit"})
    chunks = bytearray()
    async for chunk in request.stream():
        chunks.extend(chunk)
        if len(chunks) > 10_000_000:
            raise HTTPException(413, detail={"code": "MEDIA_TOO_LARGE", "message": "Image exceeds the 10 MB limit"})
    authorized_id, _seller_id = SellerMediaService._decode_token(token)
    if authorized_id != asset_id:
        raise HTTPException(403, detail={"code": "UPLOAD_SIGNATURE_INVALID", "message": "Upload authorization does not match this asset"})
    await SellerMediaService(db).accept_upload(token, bytes(chunks))
    await db.commit()
    return Response(status_code=204)


@router.post("/api/v1/seller/media/uploads/{asset_id}/complete", response_model=SellerMediaStatusResponse, status_code=202)
async def complete_upload(asset_id: UUID, seller: Seller = Depends(require_seller_permission("catalog.write")), db: AsyncSession = Depends(get_db)) -> SellerMediaStatusResponse:
    asset = await SellerMediaService(db).complete(seller.id, asset_id)
    await db.commit()
    return SellerMediaStatusResponse(id=asset.id, state=asset.state, error_code=asset.error_code, content_type=asset.content_type, width=asset.width, height=asset.height)


@router.get("/api/v1/seller/media/uploads/{asset_id}", response_model=SellerMediaStatusResponse)
async def get_upload_status(asset_id: UUID, seller: Seller = Depends(get_current_seller), db: AsyncSession = Depends(get_db)) -> SellerMediaStatusResponse:
    asset = await SellerMediaService(db).get_owned(seller.id, asset_id)
    return SellerMediaStatusResponse(id=asset.id, state=asset.state, error_code=asset.error_code, content_type=asset.content_type, width=asset.width, height=asset.height)


@router.get("/api/v1/media/public/{asset_id}")
async def get_public_media(asset_id: UUID, db: AsyncSession = Depends(get_db)) -> FileResponse:
    asset = await db.get(SellerMediaAsset, asset_id)
    if asset is None or asset.state != "READY" or not asset.content_type:
        raise HTTPException(404, detail={"code": "MEDIA_NOT_FOUND", "message": "Media asset not found"})
    extension = "jpeg" if asset.content_type == "image/jpeg" else asset.content_type.split("/")[-1]
    target = Path(settings.media_storage_root) / "approved" / f"{asset.id}.{extension}"
    if not target.is_file():
        raise HTTPException(404, detail={"code": "MEDIA_NOT_FOUND", "message": "Media asset not found"})
    return FileResponse(target, media_type=asset.content_type, headers={"Cache-Control": "public, max-age=31536000, immutable", "X-Content-Type-Options": "nosniff"})
