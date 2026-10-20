import ipaddress
import os
from urllib.parse import urlparse


def validate_media_url(value: str) -> str:
    """Accept only HTTPS media URLs, and require the configured CDN in production."""
    parsed = urlparse(value)
    if parsed.scheme.lower() != "https" or not parsed.hostname:
        raise ValueError("image URL must use https")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("image URL must not contain credentials")

    host = parsed.hostname.lower().rstrip(".")
    if host in {"localhost", "localhost.localdomain"} or host.endswith(".local"):
        raise ValueError("image URL host is not public")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None
    if address is not None and (
        address.is_private or address.is_loopback or address.is_link_local
    ):
        raise ValueError("image URL host is not public")

    if os.getenv("APP_ENV", "development").lower() in {"production", "prod"}:
        configured = urlparse(os.getenv("MEDIA_PUBLIC_BASE_URL", ""))
        configured_host = configured.hostname.lower().rstrip(".") if configured.hostname else ""
        if configured.scheme.lower() != "https" or not configured_host or host != configured_host:
            raise ValueError("image URL must use the configured media CDN")
    return value
