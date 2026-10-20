import base64
import binascii
import json
from datetime import datetime
from typing import Any, Callable
from uuid import UUID

from fastapi import HTTPException


def _aware_datetime(value: object) -> datetime:
    if not isinstance(value, str):
        raise ValueError("cursor datetime must be a string")
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("cursor datetime must include a timezone")
    return parsed


def encode_cursor(*values: object) -> str:
    payload = [value.isoformat() if isinstance(value, datetime) else str(value) if isinstance(value, UUID) else value for value in values]
    return base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode("utf-8")).decode("ascii")


datetime_cursor = _aware_datetime


def string_cursor(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("cursor field must be a string")
    return value


def integer_cursor(value: object) -> int:
    if type(value) is not int:
        raise ValueError("cursor field must be an integer")
    return value


def decode_cursor(value: str | None, *converters: Callable[[Any], Any]) -> tuple[Any, ...] | None:
    if value is None:
        return None
    try:
        raw = base64.b64decode(value + "=" * (-len(value) % 4), altchars=b"-_", validate=True)
        payload = json.loads(raw)
        if not isinstance(payload, list) or len(payload) != len(converters):
            raise ValueError("invalid cursor shape")
        return tuple(convert(item) for convert, item in zip(converters, payload, strict=True))
    except (binascii.Error, UnicodeDecodeError, json.JSONDecodeError, ValueError, TypeError, OverflowError, AttributeError) as exc:
        raise HTTPException(status_code=422, detail={"code": "INVALID_CURSOR", "message": "Invalid pagination cursor"}) from exc
