"""Create and remove ephemeral Seller QA data in staging.

This module is intentionally usable only through the root-owned staging
wrapper.  It never enables itself in production and never writes credentials
to the repository.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import secrets
import sys
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import delete, select

from src.core.config import settings
from src.core.database import AsyncSessionLocal, engine
from src.core.security import hash_password
from src.models.product import Product, ProductStatus
from src.models.seller import Seller
from src.models.seller_membership import SellerMembership
from src.models.seller_user import SellerUser
from src.models.sku import SKU

RUN_ID_RE = re.compile(r"^qa-[a-z0-9][a-z0-9-]{7,63}$")


def validate_run_id(value: str) -> str:
    if not RUN_ID_RE.fullmatch(value):
        raise ValueError("run_id must match qa-[a-z0-9][a-z0-9-]{7,63}")
    return value


def build_credentials(run_id: str) -> tuple[str, str, str]:
    validate_run_id(run_id)
    # `.test` is intentionally rejected by pydantic-email-validator as a
    # special-use domain. Use a reserved-for-internal staging suffix that
    # still exercises the same production email validation rules.
    email = f"{run_id}@staging.neomarket.internal"
    password = f"Qa-{secrets.token_urlsafe(18)}-9a"
    company = f"NeoMarket QA {run_id}"
    return email, password, company


async def create_fixture(run_id: str) -> None:
    email, password, company = build_credentials(run_id)
    now = datetime.now(timezone.utc)
    seller_id = uuid4()
    password_hash = hash_password(password)

    async with AsyncSessionLocal() as session:
        existing = await session.scalar(select(Seller).where(Seller.company_name == company))
        if existing is not None:
            raise RuntimeError(f"fixture already exists for {run_id}")

        seller = Seller(
            id=seller_id,
            email=email,
            hashed_password=password_hash,
            company_name=company,
            is_active=True,
            account_status="ACTIVE",
            email_verified_at=now,
        )
        user = SellerUser(
            id=seller_id,
            email=email,
            hashed_password=password_hash,
            is_active=True,
            email_verified_at=now,
        )
        membership = SellerMembership(
            id=uuid4(), seller_id=seller_id, user_id=seller_id, role="OWNER", active=True
        )
        product_id = uuid4()
        product = Product(
            id=product_id,
            seller_id=seller_id,
            title=f"QA Product {run_id}",
            slug=f"qa-product-{run_id}",
            description="Ephemeral staging QA fixture",
            status=ProductStatus.CREATED.value,
            is_active=False,
            deleted=False,
            images=[],
            characteristics={},
            field_reports=[],
            revision=1,
        )
        sku = SKU(
            id=uuid4(),
            product_id=product_id,
            name="Default QA SKU",
            price=1999,
            stock=5,
            on_hand=5,
            reserved_quantity=0,
            images=[],
            seller_article=f"QA-{run_id}",
            currency="RUB",
            options={},
            is_active=True,
        )
        # The fixture intentionally uses scalar foreign keys, so make the
        # parent rows durable before inserting membership/product dependants.
        session.add_all([seller, user])
        await session.flush()
        session.add_all([membership, product, sku])
        await session.commit()

    print(json.dumps({
        "run_id": run_id,
        "email": email,
        "password": password,
        "seller_id": str(seller_id),
        "product_id": str(product_id),
        "warning": "Ephemeral staging credentials. Destroy this fixture after QA.",
    }, sort_keys=True))


async def destroy_fixture(run_id: str) -> None:
    validate_run_id(run_id)
    company = f"NeoMarket QA {run_id}"
    async with AsyncSessionLocal() as session:
        seller = await session.scalar(select(Seller).where(Seller.company_name == company))
        if seller is None:
            print(json.dumps({"run_id": run_id, "deleted": False, "reason": "not_found"}))
            return
        user_ids = list(
            await session.scalars(
                select(SellerMembership.user_id).where(SellerMembership.seller_id == seller.id)
            )
        )
        # SQLAlchemy's default relationship synchronisation can try to NULL
        # the non-nullable products.seller_id before the database CASCADE runs.
        # Delete fixture-owned products/SKUs explicitly, then remove the
        # seller and its remaining database-cascaded rows.
        product_ids = list(
            await session.scalars(select(Product.id).where(Product.seller_id == seller.id))
        )
        if product_ids:
            await session.execute(delete(SKU).where(SKU.product_id.in_(product_ids)))
            await session.execute(delete(Product).where(Product.id.in_(product_ids)))
        await session.delete(seller)
        if user_ids:
            await session.execute(delete(SellerUser).where(SellerUser.id.in_(user_ids)))
        await session.commit()
    print(json.dumps({"run_id": run_id, "deleted": True}))


async def main(action: str, run_id: str) -> None:
    if settings.app_env.lower() != "staging":
        raise RuntimeError("B2B QA fixture is allowed only when APP_ENV=staging")
    if action == "create":
        await create_fixture(run_id)
    elif action == "destroy":
        await destroy_fixture(run_id)
    else:
        raise ValueError("action must be create or destroy")
    await engine.dispose()


def cli() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("create", "destroy"))
    parser.add_argument("run_id")
    args = parser.parse_args()
    try:
        asyncio.run(main(args.action, validate_run_id(args.run_id)))
    except Exception as exc:  # noqa: BLE001 - command must return a useful nonzero error
        print(f"fixture failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(cli())
