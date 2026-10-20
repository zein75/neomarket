from sqlalchemy import BigInteger, SmallInteger, String
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class AuditChainHead(Base):
    __tablename__ = "audit_chain_heads"

    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    last_sequence: Mapped[int] = mapped_column(BigInteger, nullable=False)
    last_hash: Mapped[str] = mapped_column(String(64), nullable=False)
