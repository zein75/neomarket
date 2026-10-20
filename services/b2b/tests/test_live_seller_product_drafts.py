import asyncio
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from datetime import datetime, timezone
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.core.security import hash_password
from src.models.category import Category
from src.models.product import Product, ProductStatus
from src.models.product_version import ProductVersion
from src.models.outbox_event import OutboxEvent
from src.models.seller import Seller
from src.models.seller_membership import SellerMembership
from src.models.seller_product_creation import SellerProductCreation
from src.models.seller_user import SellerUser
from src.models.sku import SKU


class _DropResponseProxy(ThreadingHTTPServer):
    upstream_url: str
    upstream_status: int | None = None


class _DropResponseHandler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
        upstream = httpx.post(
            f"{self.server.upstream_url}{self.path}",  # type: ignore[attr-defined]
            content=body,
            headers={
                "Authorization": self.headers["Authorization"],
                "Content-Type": self.headers.get("Content-Type", "application/json"),
                "Idempotency-Key": self.headers["Idempotency-Key"],
            },
            timeout=20,
        )
        self.server.upstream_status = upstream.status_code  # type: ignore[attr-defined]
        self.close_connection = True
        self.connection.close()

    def log_message(self, _format: str, *_args: object) -> None:
        return


@pytest.mark.postgres_integration
def test_live_twenty_variant_product_draft_is_atomic_and_idempotent() -> None:
    database_url = os.getenv("NEOMARKET_POSTGRES_TEST_URL")
    b2b_url = os.getenv("NEOMARKET_B2B_TEST_URL")
    if not database_url or not b2b_url:
        pytest.skip("set PostgreSQL and B2B URLs for product-draft integration")

    async def scenario() -> None:
        engine = create_async_engine(database_url)
        sessions = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
        seller_id, user_id = uuid4(), uuid4()
        email = f"seller-draft-{uuid4()}@example.com"
        password = "DisposableDraft!2026"
        product_id = None
        try:
            async with sessions() as session:
                category = await session.scalar(
                    select(Category).where(Category.is_active.is_(True)).limit(1)
                )
                assert category is not None, "local test database needs an active category"
                now = datetime.now(timezone.utc)
                password_hash = hash_password(password)
                seller = Seller(
                    id=seller_id,
                    email=email,
                    hashed_password=password_hash,
                    company_name="Disposable seller draft integration",
                    is_active=True,
                    account_status="ACTIVE",
                    email_verified_at=now,
                )
                user = SellerUser(
                    id=user_id,
                    email=email,
                    hashed_password=password_hash,
                    is_active=True,
                    email_verified_at=now,
                )
                session.add_all([seller, user])
                await session.commit()
                session.add(
                    SellerMembership(
                        seller_id=seller_id,
                        user_id=user_id,
                        role="OWNER",
                        active=True,
                    )
                )
                await session.commit()
                category_id = category.id

            payload = {
                "title": "Disposable 20 variant draft",
                "description": "Atomic draft integration fixture",
                "category_id": str(category_id),
                "attributes": {"manufacturer": "ExampleCo"},
                "media_ids": [],
                "variants": [
                    {
                        "seller_article": f"DRAFT-{index:03}",
                        "name": f"Draft variant {index}",
                        "price_minor": 12_550 + index,
                        "currency": "RUB",
                        "on_hand": index + 4,
                        "options": {"color": f"color-{index}"},
                    }
                    for index in range(20)
                ],
            }
            with httpx.Client(timeout=20) as client:
                login = client.post(
                    f"{b2b_url}/auth/login",
                    data={"username": email, "password": password},
                )
                assert login.status_code == 200
                headers = {
                    "Authorization": f"Bearer {login.json()['access_token']}",
                    "Idempotency-Key": str(uuid4()),
                }
                proxy = _DropResponseProxy(
                    ("127.0.0.1", 0), _DropResponseHandler
                )
                proxy.upstream_url = b2b_url
                proxy_thread = Thread(target=proxy.serve_forever, daemon=True)
                proxy_thread.start()
                try:
                    with pytest.raises(httpx.TransportError):
                        client.post(
                            f"http://127.0.0.1:{proxy.server_port}/seller/v1/products/drafts",
                            headers=headers,
                            json=payload,
                        )
                    assert proxy.upstream_status == 201
                finally:
                    proxy.shutdown()
                    proxy.server_close()
                    proxy_thread.join(timeout=5)

                created = client.post(
                    f"{b2b_url}/seller/v1/products/drafts",
                    headers=headers,
                    json=payload,
                )
                assert created.status_code == 201, created.text
                body = created.json()
                product_id = body["id"]
                operation_id = body["operation_id"]
                assert body["status"] == "DRAFT"
                assert body["revision"] == 1
                assert len(body["variants"]) == 20
                assert body["variants"][0]["price_minor"] == 12_550
                assert body["variants"][0]["options"] == {"color": "color-0"}

                replay = client.post(
                    f"{b2b_url}/seller/v1/products/drafts",
                    headers=headers,
                    json=payload,
                )
                assert replay.status_code == 201
                assert replay.json()["id"] == product_id
                assert replay.json()["operation_id"] == operation_id

                second_replay = client.post(
                    f"{b2b_url}/seller/v1/products/drafts",
                    headers=headers,
                    json=payload,
                )
                assert second_replay.status_code == 201
                assert second_replay.json()["id"] == product_id

                changed = {**payload, "description": "A different command"}
                conflict = client.post(
                    f"{b2b_url}/seller/v1/products/drafts",
                    headers=headers,
                    json=changed,
                )
                assert conflict.status_code == 409

                extra_variants = [
                    {
                        "seller_article": f"DRAFT-{index:03}",
                        "name": f"Draft variant {index}",
                        "price_minor": 12_550 + index,
                        "currency": "RUB",
                        "on_hand": index + 4,
                        "options": {"color": f"color-{index}"},
                    }
                    for index in range(20, 101)
                ]
                too_many = {**payload, "variants": [*payload["variants"], *extra_variants]}
                oversized = client.post(
                    f"{b2b_url}/seller/v1/products/drafts",
                    headers={**headers, "Idempotency-Key": str(uuid4())},
                    json=too_many,
                )
                assert oversized.status_code == 422, oversized.text

                invalid_variant = {
                    **payload,
                    "variants": [
                        payload["variants"][0],
                        {**payload["variants"][1], "price_minor": -1},
                    ],
                }
                invalid_response = client.post(
                    f"{b2b_url}/seller/v1/products/drafts",
                    headers={**headers, "Idempotency-Key": str(uuid4())},
                    json=invalid_variant,
                )
                assert invalid_response.status_code == 422, invalid_response.text

                duplicate = {**payload, "variants": [payload["variants"][0], {**payload["variants"][1], "seller_article": "draft-000"}]}
                duplicate_response = client.post(
                    f"{b2b_url}/seller/v1/products/drafts",
                    headers={**headers, "Idempotency-Key": str(uuid4())},
                    json=duplicate,
                )
                assert duplicate_response.status_code == 422

                unsupported_media = {**payload, "media_ids": [str(uuid4())]}
                media_response = client.post(
                    f"{b2b_url}/seller/v1/products/drafts",
                    headers={**headers, "Idempotency-Key": str(uuid4())},
                    json=unsupported_media,
                )
                assert media_response.status_code == 404, media_response.text

            async with sessions() as session:
                product = await session.get(Product, product_id)
                assert product is not None
                assert product.status == "CREATED"
                assert product.is_active is False
                assert product.characteristics == {"manufacturer": "ExampleCo"}
                rows = list((await session.scalars(select(SKU).where(SKU.product_id == product_id))).all())
                assert len(rows) == 20
                assert len({row.seller_article.casefold() for row in rows}) == 20
                assert all(row.currency == "RUB" for row in rows)
                assert all(row.options == {"color": f"color-{index}"} for index, row in enumerate(sorted(rows, key=lambda sku: sku.seller_article)))
                assert all(row.price >= 12_550 and row.on_hand is not None for row in rows)
                receipt_count = await session.scalar(
                    select(func.count()).select_from(SellerProductCreation).where(
                        SellerProductCreation.seller_id == seller_id
                    )
                )
                assert receipt_count == 1
                product_count = await session.scalar(
                    select(func.count()).select_from(Product).where(
                        Product.seller_id == seller_id
                    )
                )
                assert product_count == 1, "rejected batches must not leave partial products"
                versions = list((await session.scalars(
                    select(ProductVersion).where(ProductVersion.product_id == product_id).order_by(ProductVersion.revision)
                )).all())
                assert [version.revision for version in versions] == [1]
                assert versions[0].snapshot_hash
                assert versions[0].is_published is False

            legacy_url = f"{b2b_url}/api/v1/products/{product_id}"
            auth_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
            with httpx.Client(timeout=20) as client:
                unversioned = client.put(
                    legacy_url,
                    headers=auth_headers,
                    json={"description": "This update has no revision precondition."},
                )
                assert unversioned.status_code in {400, 422}, unversioned.text
                stale = client.put(
                    legacy_url,
                    headers={**auth_headers, "If-Match": '"2"'},
                    json={"description": "This stale update must not be saved."},
                )
                assert stale.status_code == 412, stale.text
                current = client.put(
                    legacy_url,
                    headers={**auth_headers, "If-Match": '"1"'},
                    json={"description": "Legacy route accepted revision one."},
                )
                assert current.status_code == 200, current.text
                assert current.json()["revision"] == 2
                stale_after_write = client.put(
                    legacy_url,
                    headers={**auth_headers, "If-Match": '"1"'},
                    json={"description": "A stale legacy write must not overwrite revision two."},
                )
                assert stale_after_write.status_code == 412, stale_after_write.text
                current_read = client.get(
                    f"{b2b_url}/api/v1/seller/products/{product_id}",
                    headers=auth_headers,
                )
                assert current_read.status_code == 200
                assert current_read.json()["revision"] == 2
                assert current_read.json()["description"] == "Legacy route accepted revision one."

                ticket_id = uuid4()
                moderation_headers = {"X-Service-Key": "dev-service-key-change-in-production"}
                approval = client.post(
                    f"{b2b_url}/internal/v1/events/moderation",
                    headers=moderation_headers,
                    json={
                        "schema_version": 1,
                        "event_id": str(uuid4()),
                        "event_type": "moderation.approved",
                        "producer": "admin",
                        "aggregate_type": "moderation_ticket",
                        "aggregate_id": str(ticket_id),
                        "aggregate_version": 1,
                        "occurred_at": datetime.now(timezone.utc).isoformat(),
                        "correlation_id": str(uuid4()),
                        "payload": {
                            "product_id": str(product_id),
                            "reviewed_revision": 2,
                            "decision_id": str(uuid4()),
                            "ticket_id": str(ticket_id),
                            "actor_id": str(uuid4()),
                            "action": "APPROVE",
                        },
                    },
                )
                assert approval.status_code == 202, approval.text
                public_before_edit = client.get(
                    f"{b2b_url}/products/{product_id}", headers=moderation_headers
                )
                assert public_before_edit.status_code == 200, public_before_edit.text
                assert public_before_edit.json()["description"] == "Legacy route accepted revision one."

                pending_edit = client.put(
                    f"{b2b_url}/api/v1/seller/products/{product_id}",
                    headers={**auth_headers, "If-Match": '"2"'},
                    json={"description": "Unapproved integration update."},
                )
                assert pending_edit.status_code == 200, pending_edit.text
                assert pending_edit.json()["revision"] == 3
                public_during_review = client.get(
                    f"{b2b_url}/products/{product_id}", headers=moderation_headers
                )
                assert public_during_review.status_code == 200, public_during_review.text
                assert public_during_review.json()["description"] == "Legacy route accepted revision one."

                stale_decision = client.post(
                    f"{b2b_url}/internal/v1/events/moderation",
                    headers=moderation_headers,
                    json={
                        "schema_version": 1,
                        "event_id": str(uuid4()),
                        "event_type": "moderation.approved",
                        "producer": "admin",
                        "aggregate_type": "moderation_ticket",
                        "aggregate_id": str(uuid4()),
                        "aggregate_version": 1,
                        "occurred_at": datetime.now(timezone.utc).isoformat(),
                        "correlation_id": str(uuid4()),
                        "payload": {
                            "product_id": str(product_id),
                            "reviewed_revision": 2,
                            "decision_id": str(uuid4()),
                            "ticket_id": str(uuid4()),
                            "actor_id": str(uuid4()),
                            "action": "APPROVE",
                        },
                    },
                )
                assert stale_decision.status_code == 409, stale_decision.text
            async with sessions() as session:
                versions = list((await session.scalars(
                    select(ProductVersion).where(ProductVersion.product_id == product_id).order_by(ProductVersion.revision)
                )).all())
                assert [version.revision for version in versions] == [1, 2, 3]
                assert versions[0].snapshot["description"] == "Atomic draft integration fixture"
                assert versions[1].snapshot["description"] == "Legacy route accepted revision one."
                assert versions[2].snapshot["description"] == "Unapproved integration update."
                assert versions[0].snapshot_hash != versions[1].snapshot_hash != versions[2].snapshot_hash
                assert [version.is_published for version in versions] == [False, True, False]

                blocked_product = await session.get(Product, product_id)
                assert blocked_product is not None
                blocked_product.status = ProductStatus.BLOCKED
                blocked_revision = blocked_product.revision
                moderation_events_before = await session.scalar(
                    select(func.count()).select_from(OutboxEvent).where(
                        OutboxEvent.aggregate_id == product_id,
                        OutboxEvent.destination == "MODERATION",
                    )
                )
                await session.commit()

            autosave_url = f"{b2b_url}/api/v1/seller/products/{product_id}"
            with httpx.Client(timeout=20) as client:
                autosaved = client.patch(
                    autosave_url,
                    headers={**auth_headers, "If-Match": f'"{blocked_revision}"'},
                    json={
                        "title": "Autosaved rejected product",
                        "description": "Saved correction, still blocked until explicit submit.",
                        "characteristics": [{"name": "material", "value": "steel"}],
                    },
                )
                assert autosaved.status_code == 200, autosaved.text
                assert autosaved.json()["revision"] == blocked_revision + 1
                assert autosaved.json()["status"] == "BLOCKED"

                stale_autosave = client.patch(
                    autosave_url,
                    headers={**auth_headers, "If-Match": f'"{blocked_revision}"'},
                    json={"description": "This stale local edit must not overwrite revision four."},
                )
                assert stale_autosave.status_code == 412, stale_autosave.text

                async def count_moderation_events() -> int:
                    async with sessions() as session:
                        return int(await session.scalar(
                            select(func.count()).select_from(OutboxEvent).where(
                                OutboxEvent.aggregate_id == product_id,
                                OutboxEvent.destination == "MODERATION",
                            )
                        ) or 0)

                assert await count_moderation_events() == moderation_events_before

                explicitly_submitted = client.put(
                    autosave_url,
                    headers={**auth_headers, "If-Match": f'"{blocked_revision + 1}"'},
                    json={
                        "title": "Autosaved rejected product",
                        "description": "Saved correction, still blocked until explicit submit.",
                        "characteristics": [{"name": "material", "value": "steel"}],
                    },
                )
                assert explicitly_submitted.status_code == 200, explicitly_submitted.text
                assert explicitly_submitted.json()["revision"] == blocked_revision + 2
                assert explicitly_submitted.json()["status"] == "ON_MODERATION"

            async with sessions() as session:
                persisted = await session.get(Product, product_id)
                assert persisted is not None
                assert persisted.revision == blocked_revision + 2
                assert persisted.status == ProductStatus.ON_MODERATION
                assert persisted.description == "Saved correction, still blocked until explicit submit."
                versions = list((await session.scalars(
                    select(ProductVersion).where(ProductVersion.product_id == product_id).order_by(ProductVersion.revision)
                )).all())
                assert [version.revision for version in versions] == [1, 2, 3, blocked_revision + 1, blocked_revision + 2]
                assert versions[3].snapshot["title"] == "Autosaved rejected product"
                assert versions[3].is_published is False
                assert versions[4].is_published is False
                moderation_events_after = await session.scalar(
                    select(func.count()).select_from(OutboxEvent).where(
                        OutboxEvent.aggregate_id == product_id,
                        OutboxEvent.destination == "MODERATION",
                    )
                )
                assert moderation_events_after == moderation_events_before + 1

        finally:
            async with sessions() as session:
                await session.execute(
                    delete(SellerProductCreation).where(
                        SellerProductCreation.seller_id == seller_id
                    )
                )
                if product_id is not None:
                    product = await session.get(Product, product_id)
                    if product is not None:
                        await session.delete(product)
                await session.execute(
                    delete(SellerMembership).where(SellerMembership.user_id == user_id)
                )
                user = await session.get(SellerUser, user_id)
                if user is not None:
                    await session.delete(user)
                seller = await session.get(Seller, seller_id)
                if seller is not None:
                    await session.delete(seller)
                await session.commit()
            await engine.dispose()

    asyncio.run(scenario())
