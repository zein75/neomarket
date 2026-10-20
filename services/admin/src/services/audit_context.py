from contextvars import ContextVar, Token
from dataclasses import dataclass
from typing import Iterable
from uuid import UUID


@dataclass(frozen=True)
class AuditContext:
    request_id: str | None = None
    correlation_id: str | None = None
    actor_id: UUID | None = None
    actor_roles: tuple[str, ...] = ()


_current_audit_context: ContextVar[AuditContext] = ContextVar(
    "admin_audit_context", default=AuditContext()
)


def bind_request_context(request_id: str | None) -> Token[AuditContext]:
    return _current_audit_context.set(
        AuditContext(request_id=request_id, correlation_id=request_id)
    )


def reset_request_context(token: Token[AuditContext]) -> None:
    _current_audit_context.reset(token)


def bind_actor_context(actor_id: UUID, roles: Iterable[str]) -> None:
    current = _current_audit_context.get()
    _current_audit_context.set(
        AuditContext(
            request_id=current.request_id,
            correlation_id=current.correlation_id,
            actor_id=actor_id,
            actor_roles=tuple(sorted({str(role) for role in roles})),
        )
    )


def current_audit_context() -> AuditContext:
    return _current_audit_context.get()
