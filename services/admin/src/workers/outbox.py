import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import delete, func, select

from shared.utils.metrics import record_worker_metric
from src.core.config import settings
from src.core.database import AsyncSessionLocal
from src.models.admin_oidc_token_receipt import AdminOidcTokenReceipt
from src.models.admin_web_session import AdminWebSession
from src.models.audit_export import AuditExportArtifact
from src.models.moderation_outbox_event import ModerationOutboxEvent
from src.services.moderation_service import ModerationService
from src.services.runtime_settings import effective_values

logger = logging.getLogger(__name__)
_HEARTBEAT = Path("/tmp/admin-worker-heartbeat")


async def moderation_outbox_worker(stop: asyncio.Event) -> None:
    loop = asyncio.get_running_loop()
    next_cleanup = 0.0
    last_delivery_failures: tuple[int, int] | None = None
    last_cycle_error: str | None = None
    while not stop.is_set():
        poll_interval_seconds = settings.moderation_outbox_poll_interval_seconds
        try:
            record_worker_metric("admin_moderation_outbox", "iterations")
            async with AsyncSessionLocal() as session:
                workflow_settings, _ = await effective_values(session, "workflow_settings")
                poll_interval_seconds = float(workflow_settings["moderation_outbox_poll_interval_seconds"])
                delivered = await ModerationService(session).retry_pending_decisions()
                retry_count = int(await session.scalar(
                    select(func.count()).select_from(ModerationOutboxEvent).where(ModerationOutboxEvent.status == "RETRY")
                ) or 0)
                dead_count = int(await session.scalar(
                    select(func.count()).select_from(ModerationOutboxEvent).where(ModerationOutboxEvent.status == "DEAD")
                ) or 0)
                record_worker_metric("admin_moderation_outbox", "delivered", delivered)
                await session.commit()
            if loop.time() >= next_cleanup:
                async with AsyncSessionLocal() as session:
                    result = await session.execute(delete(AuditExportArtifact).where(
                        AuditExportArtifact.expires_at <= datetime.now(timezone.utc)
                    ))
                    await session.commit()
                    record_worker_metric("admin_audit_export", "expired_deleted", max(0, int(result.rowcount or 0)))
                async with AsyncSessionLocal() as session:
                    now = datetime.now(timezone.utc)
                    await session.execute(delete(AdminOidcTokenReceipt).where(AdminOidcTokenReceipt.expires_at <= now))
                    result = await session.execute(delete(AdminWebSession).where(
                        (AdminWebSession.oidc_token_expires_at <= now)
                        | (
                            AdminWebSession.oidc_jti_hash.is_(None)
                            & (
                                (AdminWebSession.idle_expires_at <= now)
                                | (AdminWebSession.absolute_expires_at <= now)
                                | (AdminWebSession.revoked_at <= now - timedelta(days=1))
                            )
                        )
                    ))
                    await session.commit()
                    record_worker_metric("admin_web_session", "expired_deleted", max(0, int(result.rowcount or 0)))
                next_cleanup = loop.time() + 60
            heartbeat = _HEARTBEAT.with_suffix(".tmp")
            heartbeat.write_text(json.dumps({
                "updated_at": datetime.now(timezone.utc).timestamp(),
                "retry": retry_count,
                "dead": dead_count,
            }), encoding="utf-8")
            heartbeat.replace(_HEARTBEAT)
            if last_cycle_error is not None:
                logger.info("Admin outbox worker DB cycle recovered")
                last_cycle_error = None
            delivery_failures = (retry_count, dead_count)
            if delivery_failures != last_delivery_failures:
                if retry_count or dead_count:
                    logger.error("Admin outbox has delivery failures: retry=%d dead=%d", retry_count, dead_count)
                elif last_delivery_failures is not None:
                    logger.info("Admin outbox delivery failures cleared")
                last_delivery_failures = delivery_failures
        except Exception as exc:  # noqa: BLE001 - worker must survive transient DB/B2B failures
            record_worker_metric("admin_moderation_outbox", "failures")
            error_type = type(exc).__name__
            if error_type != last_cycle_error:
                logger.error("Admin outbox worker DB cycle failed (%s)", error_type)
                last_cycle_error = error_type
        try:
            await asyncio.wait_for(stop.wait(), timeout=poll_interval_seconds)
        except TimeoutError:
            continue
