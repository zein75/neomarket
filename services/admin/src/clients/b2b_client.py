from typing import Any
from uuid import UUID

import httpx
from fastapi import HTTPException

from src.core.config import settings
from shared.utils.service_auth import service_headers


class B2BClient:
    async def submit_safety_command(self, command: dict[str, Any]) -> dict[str, Any]:
        command_id = str(command.get("command_id", ""))
        command_type = command.get("command_type")
        aggregate_id = str(command.get("aggregate_id", ""))
        expected_version = command.get("expected_version")
        try:
            command_id = str(UUID(command_id))
            aggregate_id = str(UUID(aggregate_id))
        except ValueError as exc:
            raise HTTPException(status_code=422, detail={"code": "INVALID_ADMIN_COMMAND", "message": "Admin command IDs must be UUIDs"}) from exc
        if command_type == "PRODUCT_SAFETY_HOLD":
            path = f"/internal/v1/products/{aggregate_id}/safety-hold"
        elif command_type == "SELLER_RESTRICTION":
            path = f"/internal/v1/sellers/{aggregate_id}/restrictions"
        else:
            raise HTTPException(status_code=422, detail={"code": "INVALID_ADMIN_COMMAND", "message": "Unsupported Admin command type"})
        if not command_id or not aggregate_id or not isinstance(expected_version, int) or expected_version < 1:
            raise HTTPException(status_code=422, detail={"code": "INVALID_ADMIN_COMMAND", "message": "Admin command is missing its ID, aggregate, or expected version"})
        try:
            async with httpx.AsyncClient(timeout=settings.b2b_timeout_seconds) as client:
                response = await client.post(
                    f"{settings.b2b_base_url.rstrip('/')}{path}",
                    json=command,
                    headers={
                        **service_headers(settings, audience="neomarket-b2b"),
                        "Idempotency-Key": command_id,
                        "If-Match": f'"{expected_version}"',
                    },
                )
                response.raise_for_status()
                return self._command_receipt(response.json(), command_id)
        except httpx.HTTPStatusError as exc:
            detail = self._response_detail(exc.response)
            if exc.response.status_code == 404 and detail.get("code") == "B2B_ENDPOINT_UNAVAILABLE":
                raise HTTPException(status_code=503, detail={"code": "B2B_ADMIN_COMMAND_UNAVAILABLE", "message": "B2B does not expose the Admin command contract"}) from exc
            if exc.response.status_code >= 500 or exc.response.status_code in {401, 403}:
                raise HTTPException(status_code=503, detail={"code": "B2B_UNAVAILABLE", "message": "B2B could not process the Admin command"}) from exc
            raise HTTPException(status_code=exc.response.status_code, detail=detail) from exc
        except httpx.RequestError as exc:
            raise HTTPException(status_code=503, detail={"code": "B2B_UNAVAILABLE", "message": "B2B service unavailable"}) from exc

    async def submit_taxonomy_command(self, command: dict[str, Any]) -> dict[str, Any]:
        command_id = str(command.get("command_id", ""))
        expected_version = command.get("expected_version")
        if not command_id or not isinstance(expected_version, int):
            raise HTTPException(status_code=422, detail={"code": "INVALID_TAXONOMY_COMMAND", "message": "Taxonomy command is missing its ID or expected version"})
        try:
            async with httpx.AsyncClient(timeout=settings.b2b_timeout_seconds) as client:
                response = await client.post(
                    f"{settings.b2b_base_url.rstrip('/')}/internal/v1/taxonomy/commands",
                    json=command,
                    headers={
                        **service_headers(settings, audience="neomarket-b2b"),
                        "Idempotency-Key": command_id,
                        "If-Match": f'"{expected_version}"',
                    },
                )
                response.raise_for_status()
                return self._command_receipt(response.json(), command_id)
        except httpx.HTTPStatusError as exc:
            detail = self._response_detail(exc.response)
            code = exc.response.status_code
            if code == 404 and detail.get("code") == "B2B_ENDPOINT_UNAVAILABLE":
                raise HTTPException(status_code=503, detail={"code": "B2B_TAXONOMY_COMMAND_UNAVAILABLE", "message": "B2B does not expose the Admin taxonomy command contract"}) from exc
            if code >= 500 or code in {401, 403}:
                raise HTTPException(status_code=503, detail={"code": "B2B_UNAVAILABLE", "message": "B2B could not process the Admin taxonomy command"}) from exc
            raise HTTPException(status_code=code, detail=detail) from exc
        except httpx.RequestError as exc:
            raise HTTPException(status_code=503, detail={"code": "B2B_UNAVAILABLE", "message": "B2B service unavailable"}) from exc

    async def get_taxonomy_command(self, command_id: str) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(timeout=settings.b2b_timeout_seconds) as client:
                response = await client.get(
                    f"{settings.b2b_base_url.rstrip('/')}/internal/v1/taxonomy/commands/{command_id}",
                    headers=service_headers(settings, audience="neomarket-b2b"),
                )
                response.raise_for_status()
                return self._command_receipt(response.json(), command_id)
        except httpx.HTTPStatusError as exc:
            detail = self._response_detail(exc.response)
            code = exc.response.status_code
            if code == 404 and detail.get("code") == "B2B_ENDPOINT_UNAVAILABLE":
                raise HTTPException(status_code=503, detail={"code": "B2B_TAXONOMY_COMMAND_UNAVAILABLE", "message": "B2B does not expose the Admin taxonomy command receipt contract"}) from exc
            if code >= 500 or code in {401, 403}:
                raise HTTPException(status_code=503, detail={"code": "B2B_UNAVAILABLE", "message": "B2B could not return the Admin taxonomy command receipt"}) from exc
            raise HTTPException(status_code=code, detail=detail) from exc
        except httpx.RequestError as exc:
            raise HTTPException(status_code=503, detail={"code": "B2B_UNAVAILABLE", "message": "B2B service unavailable"}) from exc

    def _command_receipt(self, body: Any, expected_command_id: str) -> dict[str, Any]:
        if not isinstance(body, dict) or body.get("command_id") != expected_command_id or body.get("status") not in {"QUEUED", "APPLIED", "CONFLICT", "REJECTED"}:
            raise HTTPException(status_code=502, detail={"code": "B2B_INVALID_COMMAND_RECEIPT", "message": "B2B returned an invalid Admin command receipt"})
        return body

    async def get_internal_json(self, path: str, *, params: dict[str, object] | None = None) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(timeout=settings.b2b_timeout_seconds) as client:
                response = await client.get(
                    f"{settings.b2b_base_url.rstrip('/')}{path}",
                    headers=service_headers(settings, audience="neomarket-b2b"),
                    params=params,
                )
                response.raise_for_status()
                value = response.json()
                if not isinstance(value, dict):
                    raise HTTPException(status_code=502, detail={"code": "B2B_INVALID_RESPONSE", "message": "B2B returned an invalid response"})
                return value
        except httpx.HTTPStatusError as exc:
            code = exc.response.status_code
            detail = self._response_detail(exc.response)
            if code == 404 and detail.get("code") == "B2B_ENDPOINT_UNAVAILABLE":
                raise HTTPException(status_code=503, detail={"code": "B2B_ENDPOINT_UNAVAILABLE", "message": "B2B does not expose the requested Admin internal endpoint"}) from exc
            if code >= 500 or code in {401, 403}:
                raise HTTPException(status_code=503, detail={"code": "B2B_UNAVAILABLE", "message": "B2B could not serve the Admin request"}) from exc
            raise HTTPException(status_code=code, detail=detail) from exc
        except httpx.RequestError as exc:
            raise HTTPException(status_code=503, detail={"code": "B2B_UNAVAILABLE", "message": "B2B service unavailable"}) from exc

    async def post_internal_json(
        self, path: str, body: dict[str, Any], *, idempotency_key: str, if_match: str
    ) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(timeout=settings.b2b_timeout_seconds) as client:
                response = await client.post(
                    f"{settings.b2b_base_url.rstrip('/')}{path}",
                    json=body,
                    headers={
                        **service_headers(settings, audience="neomarket-b2b"),
                        "Idempotency-Key": idempotency_key,
                        "If-Match": if_match,
                    },
                )
                response.raise_for_status()
                value = response.json()
                if not isinstance(value, dict):
                    raise HTTPException(status_code=502, detail={"code": "B2B_INVALID_RESPONSE", "message": "B2B returned an invalid response"})
                return value
        except httpx.HTTPStatusError as exc:
            code = exc.response.status_code
            detail = self._response_detail(exc.response)
            if code == 404 and detail.get("code") == "B2B_ENDPOINT_UNAVAILABLE":
                raise HTTPException(status_code=503, detail={"code": "B2B_ENDPOINT_UNAVAILABLE", "message": "B2B does not expose the requested Admin internal endpoint"}) from exc
            if code >= 500 or code in {401, 403}:
                raise HTTPException(status_code=503, detail={"code": "B2B_UNAVAILABLE", "message": "B2B could not serve the Admin request"}) from exc
            raise HTTPException(status_code=code, detail=detail) from exc
        except httpx.RequestError as exc:
            raise HTTPException(status_code=503, detail={"code": "B2B_UNAVAILABLE", "message": "B2B service unavailable"}) from exc

    async def send_moderation_decision(self, event: dict[str, object]) -> None:
        try:
            async with httpx.AsyncClient(
                timeout=settings.b2b_timeout_seconds,
            ) as client:
                response = await client.post(
                    f"{settings.b2b_base_url.rstrip('/')}/internal/v1/moderation/decisions",
                    json=event,
                    headers={
                        **service_headers(settings, audience="neomarket-b2b"),
                        "Idempotency-Key": str(event["correlation_id"]),
                        "If-Match": f'"{event["submitted_revision"]}"',
                    },
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
            body = response.json()
            if isinstance(body, dict):
                detail = body.get("detail", body)
                if isinstance(detail, dict):
                    return {
                        "code": str(detail.get("code") or "B2B_REQUEST_FAILED")[:64],
                        "message": str(detail.get("message") or "B2B rejected the Admin request")[:300],
                    }
                if detail == "Not Found":
                    return {"code": "B2B_ENDPOINT_UNAVAILABLE", "message": "B2B internal endpoint is not implemented"}
            return {"code": "B2B_REQUEST_FAILED", "message": "B2B rejected the Admin request"}
        except ValueError:
            return {"code": "B2B_REQUEST_FAILED", "message": "B2B rejected the Admin request"}
