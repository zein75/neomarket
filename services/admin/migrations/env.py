import os
from logging.config import fileConfig

from sqlalchemy import create_engine, pool

from alembic import context

from src.models.base import Base
from src.models.moderation import ModerationCard, ModerationSKU  # noqa: F401

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

_DEFAULT_URL = "postgresql+psycopg2://postgres:postgres@localhost:5432/neomarket_admin"
_env_url = os.getenv("DATABASE_URL", "")
if _env_url:
    _env_url = _env_url.replace("postgresql+asyncpg://", "postgresql+psycopg2://")

DATABASE_URL: str = _env_url.strip() or _DEFAULT_URL


def run_migrations_offline() -> None:
    context.configure(
        url=DATABASE_URL,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = create_engine(DATABASE_URL, poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
