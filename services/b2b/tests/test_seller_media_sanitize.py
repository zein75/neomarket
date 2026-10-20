from __future__ import annotations

import struct
import zlib

import pytest

from src.services.seller_media_service import MAX_PIXELS, SellerMediaService


def _png_header(width: int, height: int) -> bytes:
    def chunk(kind: bytes, data: bytes) -> bytes:
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IEND", b"")


def test_image_sanitizer_rejects_pixel_bomb_before_decode() -> None:
    width = 4001
    height = MAX_PIXELS // width + 1
    hostile_header = _png_header(width, height)

    with pytest.raises(ValueError, match="IMAGE_PIXEL_LIMIT"):
        SellerMediaService._sanitize(hostile_header)
