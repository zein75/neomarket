from typing import Any

import httpx
from fastapi import HTTPException

from src.core.config import settings


class B2BClient:
    async def send_moderation_decision(self, event: dict[str, object]) -> None:
        try:
            async with httpx.AsyncClient(
                timeout=settings.b2b_timeout_seconds,
            ) as client:
                response = await client.post(
                    f"{settings.b2b_base_url.rstrip('/')}/api/v1/moderation/events",
                    json=event,
                    headers={"X-Service-Key": settings.service_key},
                )
                response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise HTTPException(
                status_code=exc.response.status_code,
                detail=self._response_detail(exc.response),
            )
        except httpx.RequestError:
            raise HTTPException(status_code=503, detail="B2B service unavailable")

    def _response_detail(self, response: httpx.Response) -> Any:
        try:
            return response.json().get("detail")
        except ValueError:
            return response.text
