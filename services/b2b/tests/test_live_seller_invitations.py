import asyncio
import os
import re
import time
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.core.security import hash_password
from src.models.product import Product
from src.models.seller import Seller
from src.models.seller_invite import SellerInvite
from src.models.seller_membership import SellerMembership
from src.models.seller_user import SellerUser


def _message_token(client: httpx.Client, mailpit_url: str, email: str) -> tuple[str, str]:
    for _ in range(40):
        inbox = client.get(
            f"{mailpit_url}/api/v1/messages", params={"query": f"to:{email}"}
        )
        assert inbox.status_code == 200
        messages = inbox.json().get("messages", [])
        if messages:
            message_id = messages[0]["ID"]
            detail = client.get(f"{mailpit_url}/api/v1/message/{message_id}")
            assert detail.status_code == 200
            body = detail.json().get("Text", "")
            match = re.search(r"#token=([A-Za-z0-9_-]+)", body)
            assert match, "invitation email must carry its one-use token in the URL fragment"
            return message_id, match.group(1)
        time.sleep(0.15)
    raise AssertionError("invitation email was not delivered to local Mailpit")


@pytest.mark.postgres_integration
def test_live_invitation_acceptance_expiry_replay_login_and_role_policy() -> None:
    database_url = os.getenv("NEOMARKET_POSTGRES_TEST_URL")
    b2b_url = os.getenv("NEOMARKET_B2B_TEST_URL")
    mailpit_url = os.getenv("NEOMARKET_MAILPIT_TEST_URL")
    if not database_url or not b2b_url or not mailpit_url:
        pytest.skip("set PostgreSQL, B2B and Mailpit URLs for invitation integration")

    async def scenario() -> None:
        engine = create_async_engine(database_url)
        sessions = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
        seller_id = uuid4()
        owner_email = f"invite-owner-{uuid4()}@example.com"
        member_email = f"invite-member-{uuid4()}@example.com"
        finance_email = f"invite-finance-{uuid4()}@example.com"
        expired_email = f"invite-expired-{uuid4()}@example.com"
        owner_password = "DisposableOwner!2026"
        member_password = "DisposableMember!2026"
        product_id = uuid4()
        email_to_message_id: dict[str, str] = {}
        try:
            async with sessions() as session:
                owner = Seller(
                    id=seller_id,
                    email=owner_email,
                    hashed_password=hash_password(owner_password),
                    company_name="Disposable invited seller",
                    is_active=True,
                    account_status="ACTIVE",
                    email_verified_at=datetime.now(timezone.utc),
                )
                owner_user = SellerUser(
                    id=seller_id,
                    email=owner_email,
                    hashed_password=hash_password(owner_password),
                    is_active=True,
                    email_verified_at=datetime.now(timezone.utc),
                )
                owner_membership = SellerMembership(
                    seller_id=seller_id,
                    user_id=seller_id,
                    role="OWNER",
                    active=True,
                )
                product = Product(
                    id=product_id,
                    seller=owner,
                    title="Disposable role-gated product",
                    images=[],
                    characteristics={},
                    status="CREATED",
                    is_active=False,
                    deleted=False,
                    revision=1,
                )
                session.add_all([owner, owner_user, product])
                await session.flush()
                session.add(owner_membership)
                await session.commit()

            with httpx.Client(timeout=10) as client:
                owner_login = client.post(
                    f"{b2b_url}/auth/login",
                    data={"username": owner_email, "password": owner_password},
                )
                assert owner_login.status_code == 200
                owner_headers = {
                    "Authorization": f"Bearer {owner_login.json()['access_token']}"
                }

                first_invite = client.post(
                    f"{b2b_url}/team/invitations",
                    headers=owner_headers,
                    json={"email": member_email, "role": "VIEWER"},
                )
                assert first_invite.status_code == 201
                first_data = first_invite.json()
                expiry = datetime.fromisoformat(first_data["expires_at"].replace("Z", "+00:00"))
                remaining = expiry - datetime.now(timezone.utc)
                assert timedelta(hours=71) < remaining <= timedelta(hours=72)
                message_id, token = _message_token(client, mailpit_url, member_email)
                email_to_message_id[member_email] = message_id

                mismatch = client.post(
                    f"{b2b_url}/team/invitations/accept",
                    json={"email": expired_email, "password": member_password, "token": token},
                )
                assert mismatch.status_code == 400

                accepted = client.post(
                    f"{b2b_url}/team/invitations/accept",
                    json={"email": member_email, "password": member_password, "token": token},
                )
                assert accepted.status_code == 201
                assert accepted.json()["status"] == "ACCEPTED"
                assert accepted.json()["role"] == "VIEWER"

                replay = client.post(
                    f"{b2b_url}/team/invitations/accept",
                    json={"email": member_email, "password": member_password, "token": token},
                )
                assert replay.status_code == 400

                expired_invite = client.post(
                    f"{b2b_url}/team/invitations",
                    headers=owner_headers,
                    json={"email": expired_email, "role": "SUPPORT"},
                )
                assert expired_invite.status_code == 201
                expired_data = expired_invite.json()
                expired_message, expired_token = _message_token(
                    client, mailpit_url, expired_email
                )
                email_to_message_id[expired_email] = expired_message
                async with sessions() as session:
                    await session.execute(
                        update(SellerInvite)
                        .where(SellerInvite.id == expired_data["id"])
                        .values(expires_at=datetime.now(timezone.utc) - timedelta(seconds=1))
                    )
                    await session.commit()
                expired_acceptance = client.post(
                    f"{b2b_url}/team/invitations/accept",
                    json={
                        "email": expired_email,
                        "password": member_password,
                        "token": expired_token,
                    },
                )
                assert expired_acceptance.status_code == 400

                member_login = client.post(
                    f"{b2b_url}/auth/login",
                    data={"username": member_email, "password": member_password},
                )
                assert member_login.status_code == 200
                member_headers = {
                    "Authorization": f"Bearer {member_login.json()['access_token']}"
                }
                member_profile = client.get(
                    f"{b2b_url}/auth/me", headers=member_headers
                )
                assert member_profile.status_code == 200
                assert member_profile.json()["email"] == member_email
                assert member_profile.json()["id"] == str(seller_id)

                forbidden_edit = client.put(
                    f"{b2b_url}/api/v1/seller/products/{product_id}",
                    headers={**member_headers, "If-Match": '"1"'},
                    json={"title": "Viewer cannot edit"},
                )
                assert forbidden_edit.status_code == 403
                assert forbidden_edit.json()["code"] == "SELLER_PERMISSION_DENIED"

                finance_invite = client.post(
                    f"{b2b_url}/team/invitations",
                    headers=owner_headers,
                    json={"email": finance_email, "role": "FINANCE"},
                )
                assert finance_invite.status_code == 201
                finance_message, finance_token = _message_token(
                    client, mailpit_url, finance_email
                )
                email_to_message_id[finance_email] = finance_message
                finance_accept = client.post(
                    f"{b2b_url}/team/invitations/accept",
                    json={
                        "email": finance_email,
                        "password": member_password,
                        "token": finance_token,
                    },
                )
                assert finance_accept.status_code == 201
                assert finance_accept.json()["role"] == "FINANCE"
                finance_login = client.post(
                    f"{b2b_url}/auth/login",
                    data={"username": finance_email, "password": member_password},
                )
                assert finance_login.status_code == 200
                finance_headers = {
                    "Authorization": f"Bearer {finance_login.json()['access_token']}"
                }
                finance_edit = client.put(
                    f"{b2b_url}/api/v1/seller/products/{product_id}",
                    headers={**finance_headers, "If-Match": '"1"'},
                    json={"title": "Finance role cannot edit products"},
                )
                assert finance_edit.status_code == 403
                assert finance_edit.json()["code"] == "SELLER_PERMISSION_DENIED"

            async with sessions() as session:
                members = await session.execute(
                    select(SellerMembership).where(
                        SellerMembership.seller_id == seller_id,
                        SellerMembership.user_id != seller_id,
                    )
                )
                memberships = members.scalars().all()
                assert len(memberships) == 2
                assert {membership.role for membership in memberships} == {"VIEWER", "FINANCE"}
        finally:
            async with sessions() as session:
                product = await session.get(Product, product_id)
                if product is not None:
                    await session.delete(product)
                seller = await session.get(Seller, seller_id)
                if seller is not None:
                    await session.delete(seller)
                emails = (owner_email, member_email, finance_email, expired_email)
                users = await session.execute(
                    select(SellerUser).where(SellerUser.email.in_(emails))
                )
                for user in users.scalars().all():
                    await session.delete(user)
                await session.commit()
            if email_to_message_id:
                with httpx.Client(timeout=10) as client:
                    deleted = client.request(
                        "DELETE",
                        f"{mailpit_url}/api/v1/messages",
                        json={"IDs": list(email_to_message_id.values())},
                    )
                    assert deleted.status_code == 200
            await engine.dispose()

    asyncio.run(scenario())
