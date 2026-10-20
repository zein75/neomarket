from sqlalchemy import Integer
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class TaxonomyState(Base):
    __tablename__ = "taxonomy_state"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
