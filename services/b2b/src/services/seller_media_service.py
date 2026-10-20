import base64
import hashlib
import hmac
import io
import json
import os
import socket
import struct
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID, uuid4

from fastapi import HTTPException
from PIL import Image, ImageOps, UnidentifiedImageError
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import settings
from src.models.seller_media_asset import SellerMediaAsset
from src.schemas.seller_media import SellerMediaIntentCreate

MAX_BYTES = 10_000_000
MAX_PIXELS = 40_000_000
Image.MAX_IMAGE_PIXELS = MAX_PIXELS
ALLOWED = {"image/jpeg": "JPEG", "image/png": "PNG", "image/webp": "WEBP"}


class SellerMediaService:
    def __init__(self, session: AsyncSession):
        self.session = session

    @staticmethod
    def _encode_token(asset_id: UUID, seller_id: UUID, expires: int) -> str:
        payload = json.dumps({"a": str(asset_id), "s": str(seller_id), "e": expires}, separators=(",", ":")).encode()
        encoded = base64.urlsafe_b64encode(payload).rstrip(b"=")
        secret = settings.media_upload_signing_secret or settings.secret_key
        sig = hmac.new(secret.encode(), encoded, hashlib.sha256).digest()
        return encoded.decode() + "." + base64.urlsafe_b64encode(sig).rstrip(b"=").decode()

    @staticmethod
    def _decode_token(token: str) -> tuple[UUID, UUID]:
        try:
            body, signature = token.split(".", 1)
            secret = settings.media_upload_signing_secret or settings.secret_key
            expected = base64.urlsafe_b64encode(hmac.new(secret.encode(), body.encode(), hashlib.sha256).digest()).rstrip(b"=").decode()
            if not hmac.compare_digest(expected, signature):
                raise ValueError("signature")
            data = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
            if int(data["e"]) < int(datetime.now(timezone.utc).timestamp()):
                raise ValueError("expired")
            return UUID(data["a"]), UUID(data["s"])
        except (ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
            raise HTTPException(403, detail={"code": "UPLOAD_SIGNATURE_INVALID", "message": "Upload authorization is invalid or expired"}) from exc

    async def create_intent(self, seller_id: UUID, data: SellerMediaIntentCreate, key: str) -> tuple[SellerMediaAsset, str]:
        request_hash = hashlib.sha256(data.model_dump_json().encode()).hexdigest()
        existing = await self.session.scalar(select(SellerMediaAsset).where(SellerMediaAsset.seller_id == seller_id, SellerMediaAsset.idempotency_key == key))
        if existing:
            if existing.request_hash != request_hash:
                raise HTTPException(409, detail={"code": "IDEMPOTENCY_CONFLICT", "message": "The key was already used for a different upload"})
            asset = existing
            if asset.state in {"UPLOAD_PENDING", "UPLOADED"} and asset.upload_expires_at <= datetime.now(timezone.utc):
                asset.upload_expires_at = datetime.now(timezone.utc) + timedelta(minutes=15)
        else:
            expires_at = datetime.now(timezone.utc) + timedelta(minutes=15)
            asset = SellerMediaAsset(id=uuid4(), seller_id=seller_id, idempotency_key=key, request_hash=request_hash,
                                     expected_size=data.size, expected_content_type=data.content_type,
                                     expected_sha256=data.sha256.lower(), upload_expires_at=expires_at)
            self.session.add(asset)
            await self.session.flush()
        token = self._encode_token(asset.id, seller_id, int(asset.upload_expires_at.timestamp()))
        return asset, token

    async def accept_upload(self, token: str, body: bytes) -> None:
        asset_id, seller_id = self._decode_token(token)
        asset = await self.session.scalar(select(SellerMediaAsset).where(SellerMediaAsset.id == asset_id, SellerMediaAsset.seller_id == seller_id).with_for_update())
        if asset is None or asset.state not in {"UPLOAD_PENDING", "UPLOADED"}:
            raise HTTPException(404, detail={"code": "MEDIA_NOT_FOUND", "message": "Upload intent not found"})
        digest = hashlib.sha256(body).hexdigest()
        if len(body) != asset.expected_size or digest != asset.expected_sha256:
            raise HTTPException(422, detail={"code": "UPLOAD_CONTENT_MISMATCH", "message": "Upload size or checksum does not match the intent"})
        root = Path(settings.media_storage_root) / "quarantine"
        root.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(root, 0o700)
        target = root / f"{asset.id}.blob"
        if asset.state == "UPLOADED" and target.exists() and hashlib.sha256(target.read_bytes()).hexdigest() == digest:
            return
        temp = root / f".{asset.id}.{uuid4().hex}.tmp"
        with temp.open("xb") as stream:
            os.chmod(temp, 0o600)
            stream.write(body)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, target)
        asset.state = "UPLOADED"
        asset.uploaded_at = datetime.now(timezone.utc)

    async def complete(self, seller_id: UUID, asset_id: UUID) -> SellerMediaAsset:
        asset = await self.session.scalar(select(SellerMediaAsset).where(SellerMediaAsset.id == asset_id, SellerMediaAsset.seller_id == seller_id).with_for_update())
        if asset is None:
            raise HTTPException(404, detail={"code": "MEDIA_NOT_FOUND", "message": "Media asset not found"})
        if asset.state not in {"UPLOADED", "SCAN_QUEUED", "SCANNING", "READY"}:
            raise HTTPException(409, detail={"code": "MEDIA_UPLOAD_INCOMPLETE", "message": "Upload bytes before completing the intent"})
        if asset.state == "UPLOADED":
            asset.state = "SCAN_QUEUED"
        return asset

    async def get_owned(self, seller_id: UUID, asset_id: UUID) -> SellerMediaAsset:
        asset = await self.session.scalar(select(SellerMediaAsset).where(SellerMediaAsset.id == asset_id, SellerMediaAsset.seller_id == seller_id))
        if asset is None:
            raise HTTPException(404, detail={"code": "MEDIA_NOT_FOUND", "message": "Media asset not found"})
        return asset

    @staticmethod
    def _clam_scan(data: bytes) -> bool:
        with socket.create_connection((settings.media_scanner_host, settings.media_scanner_port), timeout=10) as client:
            client.settimeout(30)
            client.sendall(b"zINSTREAM\0")
            for offset in range(0, len(data), 64 * 1024):
                chunk = data[offset:offset + 64 * 1024]
                client.sendall(struct.pack("!I", len(chunk)) + chunk)
            client.sendall(struct.pack("!I", 0))
            response = bytearray()
            while not response.endswith(b"\0") and len(response) < 4096:
                part = client.recv(1024)
                if not part:
                    break
                response.extend(part)
        result = bytes(response).decode("utf-8", "replace").strip("\0")
        if result.endswith("OK"):
            return True
        if "FOUND" in result:
            return False
        raise RuntimeError("ClamAV scanner did not return a valid scan result")

    @classmethod
    def _sanitize(cls, data: bytes) -> tuple[bytes, str, int, int]:
        with Image.open(io.BytesIO(data)) as probe:
            if probe.format not in set(ALLOWED.values()):
                raise ValueError("UNSUPPORTED_IMAGE_FORMAT")
            if probe.width * probe.height > MAX_PIXELS:
                raise ValueError("IMAGE_PIXEL_LIMIT")
            probe.verify()
        with Image.open(io.BytesIO(data)) as image:
            if image.format not in set(ALLOWED.values()):
                raise ValueError("UNSUPPORTED_IMAGE_FORMAT")
            fmt = image.format
            image.load()
            image = ImageOps.exif_transpose(image)
            if image.mode not in {"RGB", "RGBA"}:
                image = image.convert("RGBA" if "transparency" in image.info else "RGB")
            if image.width * image.height > MAX_PIXELS:
                raise ValueError("IMAGE_PIXEL_LIMIT")
            output = io.BytesIO()
            fmt = fmt if fmt in {"JPEG", "PNG", "WEBP"} else "JPEG"
            if fmt == "JPEG" and image.mode != "RGB":
                image = image.convert("RGB")
            image.save(output, format=fmt, optimize=True, exif=b"")
            return output.getvalue(), f"image/{'jpeg' if fmt == 'JPEG' else fmt.lower()}", image.width, image.height

    @classmethod
    async def scan_once(cls, session: AsyncSession) -> bool:
        stale_scan = datetime.now(timezone.utc) - timedelta(minutes=5)
        asset = await session.scalar(select(SellerMediaAsset).where(
            or_(SellerMediaAsset.state == "SCAN_QUEUED", and_(SellerMediaAsset.state == "SCANNING", SellerMediaAsset.updated_at < stale_scan))
        ).order_by(SellerMediaAsset.created_at).with_for_update(skip_locked=True).limit(1))
        if asset is None:
            return False
        asset.state = "SCANNING"
        asset.scan_attempts += 1
        await session.commit()
        quarantine = Path(settings.media_storage_root) / "quarantine" / f"{asset.id}.blob"
        try:
            raw = quarantine.read_bytes()
            if len(raw) != asset.expected_size or hashlib.sha256(raw).hexdigest() != asset.expected_sha256:
                raise ValueError("UPLOAD_CONTENT_MISMATCH")
            try:
                virus_free = cls._clam_scan(raw)
            except OSError as exc:
                raise RuntimeError("CLAMAV_UNAVAILABLE") from exc
            if not virus_free:
                raise ValueError("MALWARE_DETECTED")
            clean, content_type, width, height = cls._sanitize(raw)
            if content_type != asset.expected_content_type:
                raise ValueError("CONTENT_TYPE_MISMATCH")
            if len(clean) > MAX_BYTES:
                raise ValueError("SANITIZED_IMAGE_TOO_LARGE")
            approved = Path(settings.media_storage_root) / "approved"
            approved.mkdir(mode=0o700, parents=True, exist_ok=True)
            os.chmod(approved, 0o700)
            target = approved / f"{asset.id}.{content_type.split('/')[-1]}"
            temp = approved / f".{asset.id}.{uuid4().hex}.tmp"
            with temp.open("xb") as stream:
                os.chmod(temp, 0o600)
                stream.write(clean)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp, target)
            asset.content_type, asset.width, asset.height = content_type, width, height
            asset.public_url = f"{settings.media_public_base_url.rstrip('/')}/{asset.id}"
            asset.state, asset.error_code = "READY", None
            quarantine.unlink(missing_ok=True)
        except (ValueError, SyntaxError, UnidentifiedImageError, Image.DecompressionBombError, OSError) as exc:
            code = str(exc) if isinstance(exc, ValueError) else "INVALID_IMAGE"
            asset.state, asset.error_code = "REJECTED", code[:64]
            quarantine.unlink(missing_ok=True)
        except Exception:
            asset.state, asset.error_code = "UPLOADED", "SCANNER_UNAVAILABLE"
            await session.commit()
            raise
        await session.commit()
        return True
