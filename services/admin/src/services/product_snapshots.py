import hashlib
import json
import re
from typing import Any


def content_digest(content: dict[str, Any]) -> str:
    serialized = json.dumps(content, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(serialized).hexdigest()


def normalize_source_digest(value: object) -> str:
    raw = str(value).removeprefix("sha256:").lower()
    if not re.fullmatch(r"[a-f0-9]{64}", raw):
        raise ValueError("source snapshot hash must be a SHA-256 hex digest")
    return raw
