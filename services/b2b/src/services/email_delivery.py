import asyncio
import smtplib
import ssl
from datetime import datetime
from email.message import EmailMessage
from urllib.parse import urlencode, urlsplit, urlunsplit

from fastapi import HTTPException, status

from src.core.config import settings


def require_email_delivery_configured() -> None:
    if not settings.email_smtp_host.strip() or not settings.email_from_address.strip():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "EMAIL_DELIVERY_UNAVAILABLE", "message": "Email delivery is not configured"},
            headers={"Retry-After": "60"},
        )


def _verification_link(token: str) -> str:
    parts = urlsplit(settings.seller_verification_url)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, parts.query, urlencode({"token": token})))


def _send(message: EmailMessage) -> None:
    timeout = 10
    if settings.email_smtp_mode == "ssl":
        server = smtplib.SMTP_SSL(
            settings.email_smtp_host,
            settings.email_smtp_port,
            timeout=timeout,
            context=ssl.create_default_context(),
        )
    else:
        server = smtplib.SMTP(
            settings.email_smtp_host,
            settings.email_smtp_port,
            timeout=timeout,
        )
    try:
        server.ehlo()
        if settings.email_smtp_mode == "starttls":
            server.starttls(context=ssl.create_default_context())
            server.ehlo()
        if settings.email_smtp_username:
            server.login(settings.email_smtp_username, settings.email_smtp_password)
        server.send_message(message)
    finally:
        try:
            server.quit()
        except (OSError, smtplib.SMTPException):
            server.close()


async def send_verification_email(email: str, token: str) -> None:
    require_email_delivery_configured()
    link = _verification_link(token)
    message = EmailMessage()
    message["Subject"] = "Подтвердите email для NeoMarket Seller"
    message["From"] = settings.email_from_address
    message["To"] = email
    message.set_content(
        "Чтобы подтвердить email и продолжить регистрацию продавца, откройте ссылку:\n\n"
        f"{link}\n\n"
        "Ссылка действует 30 минут и может быть использована один раз. "
        "Если вы не создавали аккаунт, проигнорируйте это письмо."
    )
    try:
        await asyncio.to_thread(_send, message)
    except (OSError, smtplib.SMTPException) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "EMAIL_DELIVERY_FAILED", "message": "Verification email could not be delivered"},
            headers={"Retry-After": "60"},
        ) from exc


async def send_seller_invitation_email(
    email: str, token: str, *, company_name: str, role: str, expires_at: datetime
) -> None:
    require_email_delivery_configured()
    parts = urlsplit(settings.seller_invitation_url)
    link = urlunsplit(
        (parts.scheme, parts.netloc, parts.path, parts.query, f"token={token}")
    )
    message = EmailMessage()
    message["Subject"] = "Приглашение в команду NeoMarket Seller"
    message["From"] = settings.email_from_address
    message["To"] = email
    message.set_content(
        f"Вас пригласили в магазин «{company_name}» с ролью {role}.\n\n"
        "Чтобы принять приглашение, откройте ссылку и укажите этот email.\n\n"
        f"{link}\n\n"
        f"Ссылка действует до {expires_at.isoformat()} и используется один раз. "
        "Если вы не ожидали приглашение, проигнорируйте это письмо."
    )
    try:
        await asyncio.to_thread(_send, message)
    except (OSError, smtplib.SMTPException) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "EMAIL_DELIVERY_FAILED", "message": "Seller invitation could not be delivered"},
            headers={"Retry-After": "60"},
        ) from exc
