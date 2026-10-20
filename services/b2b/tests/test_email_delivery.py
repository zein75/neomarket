from fastapi import HTTPException
import pytest

from src.services import email_delivery


def test_verification_link_keeps_token_in_url_fragment(monkeypatch) -> None:
    monkeypatch.setattr(
        "src.services.email_delivery.settings.seller_verification_url",
        "https://seller.example.test/verify-email?source=registration",
    )

    link = email_delivery._verification_link("one-time-token")

    assert link == "https://seller.example.test/verify-email?source=registration#token=one-time-token"


@pytest.mark.asyncio
async def test_email_delivery_fails_closed_without_smtp_configuration(monkeypatch) -> None:
    monkeypatch.setattr("src.services.email_delivery.settings.email_smtp_host", "")
    monkeypatch.setattr("src.services.email_delivery.settings.email_from_address", "")

    with pytest.raises(HTTPException) as exc_info:
        await email_delivery.send_verification_email("seller@example.test", "one-time-token")

    assert exc_info.value.status_code == 503


@pytest.mark.asyncio
async def test_email_delivery_message_contains_one_time_fragment_link(monkeypatch) -> None:
    captured = []
    monkeypatch.setattr("src.services.email_delivery.settings.email_smtp_host", "smtp.example.test")
    monkeypatch.setattr("src.services.email_delivery.settings.email_from_address", "seller@example.test")
    monkeypatch.setattr("src.services.email_delivery.settings.seller_verification_url", "https://seller.example.test/verify-email")
    monkeypatch.setattr(email_delivery, "_send", captured.append)

    await email_delivery.send_verification_email("buyer@example.test", "private-one-time-token")

    assert len(captured) == 1
    assert captured[0]["To"] == "buyer@example.test"
    assert "#token=private-one-time-token" in captured[0].get_content()
    assert captured[0]["Subject"] == "Подтвердите email для NeoMarket Seller"
