from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.complaint import Complaint
from src.models.moderation import ModerationCard, ModerationStatus
from src.models.moderation_outbox_event import ModerationOutboxEvent


_OUTBOX_STATUSES = ("PENDING", "RETRY", "LEASED", "WAITING_ACK", "SENT", "DEAD", "BLOCKED")
_PENDING_TICKET_STATUSES = (ModerationStatus.CREATED, ModerationStatus.PENDING)
_PENDING_OUTBOX_STATUSES = ("PENDING", "RETRY", "LEASED", "WAITING_ACK")
_COMPLAINT_STATUSES = ("NEW", "TRIAGED", "IN_REVIEW", "CLOSED", "ESCALATED")
_PENDING_COMPLAINT_STATUSES = ("NEW", "TRIAGED")
_ACTIVE_COMPLAINT_STATUSES = ("NEW", "TRIAGED", "IN_REVIEW", "ESCALATED")


async def render_operational_metrics(session: AsyncSession) -> str:
    now = datetime.now(timezone.utc)
    ticket_rows = (await session.execute(
        select(ModerationCard.status, func.count()).group_by(ModerationCard.status)
    )).all()
    ticket_counts = {str(status.value if isinstance(status, ModerationStatus) else status): int(count) for status, count in ticket_rows}
    outbox_rows = (await session.execute(
        select(ModerationOutboxEvent.status, func.count()).group_by(ModerationOutboxEvent.status)
    )).all()
    outbox_counts = {str(status): int(count) for status, count in outbox_rows}
    outbox_other = sum(count for status, count in outbox_counts.items() if status not in _OUTBOX_STATUSES)
    complaint_rows = (await session.execute(
        select(Complaint.status, func.count()).group_by(Complaint.status)
    )).all()
    complaint_counts = {str(status): int(count) for status, count in complaint_rows}

    oldest_ticket = await session.scalar(
        select(func.min(ModerationCard.created_at)).where(ModerationCard.status.in_(_PENDING_TICKET_STATUSES))
    )
    oldest_outbox = await session.scalar(
        select(func.min(ModerationOutboxEvent.created_at)).where(ModerationOutboxEvent.status.in_(_PENDING_OUTBOX_STATUSES))
    )
    oldest_waiting_ack = await session.scalar(
        select(func.min(ModerationOutboxEvent.created_at)).where(ModerationOutboxEvent.status == "WAITING_ACK")
    )
    oldest_complaint = await session.scalar(
        select(func.min(Complaint.created_at)).where(Complaint.status.in_(_PENDING_COMPLAINT_STATUSES))
    )
    overdue_complaints = int(await session.scalar(
        select(func.count()).select_from(Complaint).where(
            Complaint.status.in_(_ACTIVE_COMPLAINT_STATUSES),
            Complaint.deadline_at.is_not(None),
            Complaint.deadline_at <= now,
        )
    ) or 0)
    lines = [
        "# HELP admin_moderation_tickets Current moderation ticket count by state.",
        "# TYPE admin_moderation_tickets gauge",
    ]
    for status in ModerationStatus:
        lines.append(f'admin_moderation_tickets{{status="{status.value}"}} {ticket_counts.get(status.value, 0)}')
    lines.extend([
        "# HELP admin_complaint_cases Current complaint case count by state.",
        "# TYPE admin_complaint_cases gauge",
    ])
    for status in _COMPLAINT_STATUSES:
        lines.append(f'admin_complaint_cases{{status="{status}"}} {complaint_counts.get(status, 0)}')
    lines.extend([
        "# HELP admin_complaint_oldest_pending_seconds Age of the oldest pending complaint case.",
        "# TYPE admin_complaint_oldest_pending_seconds gauge",
        f"admin_complaint_oldest_pending_seconds {max(0, int((now - oldest_complaint).total_seconds())) if oldest_complaint else 0}",
        "# HELP admin_complaint_overdue_cases Current active complaint cases past their configured deadline.",
        "# TYPE admin_complaint_overdue_cases gauge",
        f"admin_complaint_overdue_cases {overdue_complaints}",
        "# HELP admin_moderation_oldest_pending_seconds Age of the oldest unclaimed moderation ticket.",
        "# TYPE admin_moderation_oldest_pending_seconds gauge",
        f"admin_moderation_oldest_pending_seconds {max(0, int((now - oldest_ticket).total_seconds())) if oldest_ticket else 0}",
        "# HELP admin_moderation_outbox_events Current outbox event count by state.",
        "# TYPE admin_moderation_outbox_events gauge",
    ])
    for status in _OUTBOX_STATUSES:
        lines.append(f'admin_moderation_outbox_events{{status="{status}"}} {outbox_counts.get(status, 0)}')
    lines.extend([
        f'admin_moderation_outbox_events{{status="other"}} {outbox_other}',
        "# HELP admin_moderation_outbox_oldest_pending_seconds Age of the oldest deliverable outbox event.",
        "# TYPE admin_moderation_outbox_oldest_pending_seconds gauge",
        f"admin_moderation_outbox_oldest_pending_seconds {max(0, int((now - oldest_outbox).total_seconds())) if oldest_outbox else 0}",
        "# HELP admin_moderation_outbox_oldest_waiting_ack_seconds Age of the oldest event awaiting downstream acknowledgement.",
        "# TYPE admin_moderation_outbox_oldest_waiting_ack_seconds gauge",
        f"admin_moderation_outbox_oldest_waiting_ack_seconds {max(0, int((now - oldest_waiting_ack).total_seconds())) if oldest_waiting_ack else 0}",
        "# HELP admin_moderation_outbox_dead_events Current number of dead-letter events.",
        "# TYPE admin_moderation_outbox_dead_events gauge",
        f"admin_moderation_outbox_dead_events {outbox_counts.get('DEAD', 0)}",
        "# HELP admin_metrics_snapshot_timestamp_seconds Unix timestamp when this database snapshot was collected.",
        "# TYPE admin_metrics_snapshot_timestamp_seconds gauge",
        f"admin_metrics_snapshot_timestamp_seconds {now.timestamp():.3f}",
    ])
    return "\n".join(lines) + "\n"
