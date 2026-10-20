import base64
import csv
import hashlib
import hmac
import json
import binascii
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import BinaryIO
from uuid import UUID, uuid4

from sqlalchemy import case, cast, func, or_, select, String, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.core.config import settings
from src.models.inventory_export import InventoryExportJob
from src.models.product import Product
from src.models.sku import SKU
from src.schemas.inventory_export import InventoryExportCreate


_CSV_HEADERS = (
    "Product", "SKU", "Seller article", "SKU ID", "Product status",
    "On hand", "Reserved", "Available", "Active",
)


class InventoryExportTooLarge(Exception):
    pass


class _DigestWriter:
    def __init__(self, stream: BinaryIO) -> None:
        self.stream = stream
        self.digest = hashlib.sha256()

    def write(self, value: str) -> int:
        encoded = value.encode("utf-8")
        self.digest.update(encoded)
        self.stream.write(encoded)
        return len(value)


def _csv_text(value: object | None) -> str:
    text = "" if value is None else str(value)
    if text.lstrip(" \t\r\n").startswith(("=", "+", "-", "@")):
        return "'" + text
    return text


def _request_hash(data: InventoryExportCreate) -> tuple[dict[str, object], str]:
    filters = data.model_dump(mode="json", exclude_none=True)
    encoded = json.dumps(filters, sort_keys=True, separators=(",", ":")).encode()
    return filters, hashlib.sha256(encoded).hexdigest()


def _encode_download_token(job: InventoryExportJob, expires_at: datetime) -> str:
    payload = json.dumps(
        {"job_id": str(job.id), "seller_id": str(job.seller_id), "exp": int(expires_at.timestamp())},
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    signature = hmac.new(settings.secret_key.encode(), payload, hashlib.sha256).digest()
    return ".".join(
        part.decode().rstrip("=")
        for part in (base64.urlsafe_b64encode(payload), base64.urlsafe_b64encode(signature))
    )


def _decode_download_token(token: str) -> tuple[UUID, UUID]:
    try:
        encoded, signed = token.split(".", 1)
        payload = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
        signature = base64.urlsafe_b64decode(signed + "=" * (-len(signed) % 4))
        expected = hmac.new(settings.secret_key.encode(), payload, hashlib.sha256).digest()
        if not hmac.compare_digest(signature, expected):
            raise ValueError("invalid signature")
        data = json.loads(payload)
        if int(data["exp"]) <= int(datetime.now(timezone.utc).timestamp()):
            raise ValueError("expired")
        return UUID(data["job_id"]), UUID(data["seller_id"])
    except (ValueError, KeyError, TypeError, json.JSONDecodeError, binascii.Error) as exc:
        raise ValueError("invalid or expired inventory export link") from exc


class InventoryExportService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, seller_id: UUID, idempotency_key: UUID, data: InventoryExportCreate) -> InventoryExportJob:
        filters, request_hash = _request_hash(data)
        existing = await self.session.scalar(
            select(InventoryExportJob).where(
                InventoryExportJob.seller_id == seller_id,
                InventoryExportJob.idempotency_key == idempotency_key,
            )
        )
        if existing:
            if not hmac.compare_digest(existing.request_hash, request_hash):
                raise ValueError("idempotency key was already used for another export request")
            return existing

        job = InventoryExportJob(
            id=uuid4(),
            seller_id=seller_id,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            filters=filters,
            state="PENDING",
            row_count=0,
        )
        try:
            async with self.session.begin_nested():
                self.session.add(job)
                await self.session.flush()
        except IntegrityError:
            existing = await self.session.scalar(
                select(InventoryExportJob).where(
                    InventoryExportJob.seller_id == seller_id,
                    InventoryExportJob.idempotency_key == idempotency_key,
                )
            )
            if existing and hmac.compare_digest(existing.request_hash, request_hash):
                return existing
            raise ValueError("idempotency key was already used for another export request")
        return job

    async def get(self, seller_id: UUID, job_id: UUID) -> InventoryExportJob | None:
        return await self.session.scalar(
            select(InventoryExportJob).where(
                InventoryExportJob.id == job_id,
                InventoryExportJob.seller_id == seller_id,
            )
        )

    @staticmethod
    def download_token(job: InventoryExportJob) -> str | None:
        if job.state != "READY" or not job.expires_at:
            return None
        now = datetime.now(timezone.utc)
        expires_at = job.expires_at
        if expires_at <= now:
            return None
        return _encode_download_token(job, expires_at)

    async def download_path(self, job_id: UUID, token: str) -> tuple[Path, datetime] | None:
        signed_job_id, seller_id = _decode_download_token(token)
        if signed_job_id != job_id:
            raise ValueError("inventory export link does not match this job")
        job = await self.session.scalar(
            select(InventoryExportJob).where(
                InventoryExportJob.id == job_id,
                InventoryExportJob.seller_id == seller_id,
            )
        )
        now = datetime.now(timezone.utc)
        if not job or job.state != "READY" or not job.expires_at or job.expires_at <= now:
            return None
        path = _artifact_path(job.seller_id, job.id)
        return (path, job.generated_at or job.created_at) if path.is_file() else None

    @staticmethod
    async def expire_ready(session: AsyncSession, now: datetime) -> list[tuple[UUID, UUID]]:
        result = await session.scalars(
            select(InventoryExportJob)
            .where(InventoryExportJob.state == "READY", InventoryExportJob.expires_at <= now)
            .order_by(InventoryExportJob.expires_at)
            .limit(100)
            .with_for_update(skip_locked=True)
        )
        expired = list(result)
        for job in expired:
            job.state = "EXPIRED"
            job.artifact_removed_at = now
        return [(job.seller_id, job.id) for job in expired]

    @staticmethod
    async def cleanup_terminal(session: AsyncSession, now: datetime) -> list[tuple[UUID, UUID]]:
        result = await session.scalars(
            select(InventoryExportJob)
            .where(
                InventoryExportJob.state.in_(("FAILED", "EXPIRED")),
                InventoryExportJob.artifact_removed_at.is_(None),
            )
            .order_by(InventoryExportJob.created_at)
            .limit(100)
            .with_for_update(skip_locked=True)
        )
        jobs = list(result)
        for job in jobs:
            job.artifact_removed_at = now
        return [(job.seller_id, job.id) for job in jobs]

    @staticmethod
    async def claim_next(session: AsyncSession, now: datetime) -> tuple[UUID, int] | None:
        stale = await session.execute(
            update(InventoryExportJob)
            .where(
                InventoryExportJob.state == "PROCESSING",
                InventoryExportJob.lease_expires_at <= now,
            )
            .values(
                state=case(
                    (InventoryExportJob.attempts >= 3, "FAILED"), else_="PENDING"
                ),
                failure_code=case(
                    (InventoryExportJob.attempts >= 3, "WORKER_RETRIES_EXHAUSTED"),
                    else_=None,
                ),
                lease_expires_at=None,
            )
        )
        del stale
        job = await session.scalar(
            select(InventoryExportJob)
            .where(InventoryExportJob.state == "PENDING")
            .order_by(InventoryExportJob.created_at, InventoryExportJob.id)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        if not job:
            return None
        job.state = "PROCESSING"
        job.attempts += 1
        job.lease_generation += 1
        job.lease_expires_at = now + timedelta(seconds=settings.inventory_export_processing_lease_seconds)
        return job.id, job.lease_generation

    @staticmethod
    async def process(
        job_id: UUID,
        lease_generation: int,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        temporary_path = _temporary_artifact_path(job_id, lease_generation)
        try:
            row_count, sha256, temporary_path = await _write_export(
                job_id, lease_generation, session_factory
            )
        except InventoryExportTooLarge:
            async with session_factory() as session:
                await session.execute(
                    update(InventoryExportJob).where(
                        InventoryExportJob.id == job_id,
                        InventoryExportJob.state == "PROCESSING",
                        InventoryExportJob.lease_generation == lease_generation,
                    )
                    .values(state="FAILED", failure_code="EXPORT_ROW_LIMIT_EXCEEDED", lease_expires_at=None)
                )
                await session.commit()
            temporary_path.unlink(missing_ok=True)
            return

        now = datetime.now(timezone.utc)
        async with session_factory() as session:
            job = await session.scalar(
                select(InventoryExportJob)
                .where(InventoryExportJob.id == job_id)
                .with_for_update()
            )
            if (
                not job
                or job.state != "PROCESSING"
                or job.lease_generation != lease_generation
            ):
                temporary_path.unlink(missing_ok=True)
                return
            os.replace(temporary_path, _artifact_path(job.seller_id, job.id))
            job.state = "READY"
            job.row_count = row_count
            job.sha256 = sha256
            job.generated_at = now
            job.expires_at = now + timedelta(seconds=settings.inventory_export_ttl_seconds)
            job.lease_expires_at = None
            job.failure_code = None
            await session.commit()


def _artifact_path(seller_id: UUID, job_id: UUID) -> Path:
    return Path(settings.media_storage_root) / "exports" / str(seller_id) / f"{job_id}.csv"


def _temporary_artifact_path(job_id: UUID, lease_generation: int) -> Path:
    return Path(settings.media_storage_root) / "exports" / "pending" / f"{job_id}.{lease_generation}.csv.part"


async def _write_export(
    job_id: UUID,
    lease_generation: int,
    session_factory: async_sessionmaker[AsyncSession],
) -> tuple[int, str, Path]:
    async with session_factory() as session:
        job = await session.get(InventoryExportJob, job_id)
        if (
            not job
            or job.state != "PROCESSING"
            or job.lease_generation != lease_generation
        ):
            return 0, "", _temporary_artifact_path(job_id, lease_generation)
        filters = job.filters
        seller_id = job.seller_id
        query = filters.get("query")
        status_filter = filters.get("status")
        on_hand = func.coalesce(SKU.on_hand, SKU.stock)
        statement = (
            select(
                Product.title.label("product_title"),
                SKU.name.label("sku_name"),
                SKU.seller_article.label("seller_article"),
                SKU.id.label("sku_id"),
                Product.status.label("product_status"),
                on_hand.label("stock_quantity"),
                SKU.reserved_quantity.label("reserved_quantity"),
                (on_hand - SKU.reserved_quantity).label("available_quantity"),
                SKU.is_active.label("is_active"),
            )
            .join(Product, Product.id == SKU.product_id)
            .where(Product.seller_id == seller_id, Product.deleted.is_(False))
        )
        if query:
            search = f"%{str(query).strip()}%"
            statement = statement.where(
                or_(
                    Product.title.ilike(search),
                    SKU.name.ilike(search),
                    cast(SKU.id, String).ilike(search),
                )
            )
        if status_filter == "available":
            statement = statement.where(SKU.is_active.is_(True), on_hand > SKU.reserved_quantity)
        elif status_filter == "reserved":
            statement = statement.where(SKU.reserved_quantity > 0)
        elif status_filter == "unavailable":
            statement = statement.where(SKU.is_active.is_(True), on_hand <= SKU.reserved_quantity)
        elif status_filter == "inactive":
            statement = statement.where(SKU.is_active.is_(False))

        statement = statement.order_by(Product.id, SKU.id).limit(settings.inventory_export_max_rows + 1)
        result = await session.stream(statement.execution_options(yield_per=1000))
        path = _artifact_path(seller_id, job_id)
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        temporary_path = _temporary_artifact_path(job_id, lease_generation)
        temporary_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        row_count = 0
        writer: _DigestWriter | None = None
        try:
            descriptor = os.open(temporary_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(descriptor, "wb") as binary:
                writer = _DigestWriter(binary)
                csv_writer = csv.writer(writer, lineterminator="\r\n")
                writer.write("\ufeff")
                csv_writer.writerow(_CSV_HEADERS)
                async for row in result.mappings():
                    row_count += 1
                    if row_count > settings.inventory_export_max_rows:
                        raise InventoryExportTooLarge
                    csv_writer.writerow((
                        _csv_text(row["product_title"]),
                        _csv_text(row["sku_name"]),
                        _csv_text(row["seller_article"]),
                        str(row["sku_id"]),
                        _csv_text(row["product_status"]),
                        int(row["stock_quantity"]),
                        int(row["reserved_quantity"]),
                        int(row["available_quantity"]),
                        "Yes" if row["is_active"] else "No",
                    ))
                binary.flush()
                os.fsync(binary.fileno())
            assert writer is not None
            return row_count, writer.digest.hexdigest(), temporary_path
        except Exception:
            temporary_path.unlink(missing_ok=True)
            raise
        finally:
            await result.close()


def delete_artifact(seller_id: UUID, job_id: UUID) -> None:
    path = _artifact_path(seller_id, job_id)
    path.unlink(missing_ok=True)
    pending_directory = path.parents[1] / "pending"
    for partial in pending_directory.glob(f"{job_id}.*.csv.part"):
        partial.unlink(missing_ok=True)
