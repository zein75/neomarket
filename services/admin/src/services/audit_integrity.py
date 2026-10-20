import hmac

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

GENESIS_HASH = "0" * 64


class AuditChainError(RuntimeError):
    pass


async def verify_audit_chain(session: AsyncSession) -> dict[str, int | str]:
    result = await session.execute(text("""
        SELECT sequence_no, previous_hash, integrity_hash,
               encode(digest(convert_to(previous_hash || CASE
                   WHEN integrity_version = 1 THEN jsonb_build_object(
                       'id',id,'actor_id',actor_id,'action',action,
                       'entity_type',entity_type,'entity_id',entity_id,
                       'details',details::jsonb,'created_at',created_at
                   )
                   WHEN integrity_version = 2 THEN jsonb_build_object(
                       'id',id,'actor_id',actor_id,'action',action,
                       'entity_type',entity_type,'entity_id',entity_id,
                       'details',details::jsonb,'created_at',created_at
                   ) || jsonb_build_object(
                       'integrity_version',integrity_version,
                       'request_id',request_id,
                       'correlation_id',correlation_id,
                       'actor_roles',actor_roles::jsonb,
                       'before_hash',before_hash,
                       'after_hash',after_hash,
                       'reason_code',reason_code
                   )
                   ELSE NULL
               END::text,'UTF8'),'sha256'),'hex') AS calculated_hash
          FROM audit_logs ORDER BY sequence_no
    """))
    previous_hash = GENESIS_HASH
    count = 0
    for row in result.mappings():
        count += 1
        if row["sequence_no"] != count:
            raise AuditChainError(f"Audit sequence gap at {row['sequence_no']}")
        if not hmac.compare_digest(row["previous_hash"], previous_hash):
            raise AuditChainError(f"Audit previous-hash mismatch at {row['sequence_no']}")
        if not hmac.compare_digest(row["integrity_hash"], row["calculated_hash"]):
            raise AuditChainError(f"Audit event hash mismatch at {row['sequence_no']}")
        previous_hash = row["integrity_hash"]
    head = (await session.execute(text(
        "SELECT last_sequence,last_hash FROM audit_chain_heads WHERE id=1"
    ))).mappings().one_or_none()
    if head is None or head["last_sequence"] != count or not hmac.compare_digest(head["last_hash"], previous_hash):
        raise AuditChainError("Audit chain head does not match the event log")
    return {"valid_events": count, "head_hash": previous_hash}
