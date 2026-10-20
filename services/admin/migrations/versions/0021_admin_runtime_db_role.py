"""Separate Admin runtime access from the PostgreSQL migration owner."""

import os

from alembic import context, op
import sqlalchemy as sa


revision = "0021_admin_runtime_db_role"
down_revision = "0020_session_device_meta"
branch_labels = None
depends_on = None

_ROLE = "admin_runtime"


def upgrade() -> None:
    bind = op.get_bind()
    password = os.getenv("ADMIN_RUNTIME_DB_PASSWORD", "")
    if len(password) < 32:
        raise RuntimeError("ADMIN_RUNTIME_DB_PASSWORD must contain at least 32 characters")
    password_literal = str(sa.literal(password, type_=sa.String()).compile(
        dialect=bind.dialect, compile_kwargs={"literal_binds": True}
    ))
    if context.is_offline_mode():
        op.execute("""
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'admin_runtime') THEN
        EXECUTE 'CREATE ROLE admin_runtime NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS';
    END IF;
END $$;
""")
        op.execute(f"ALTER ROLE admin_runtime WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS PASSWORD {password_literal}")
    else:
        exists = bind.execute(sa.text("SELECT 1 FROM pg_roles WHERE rolname = :role"), {"role": _ROLE}).first()
        if not exists:
            bind.exec_driver_sql("CREATE ROLE admin_runtime NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS")
        alter_role = bind.execute(
            sa.text("SELECT format('ALTER ROLE %I WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS PASSWORD %L', :role, :password)"),
            {"role": _ROLE, "password": password},
        ).scalar_one()
        bind.exec_driver_sql(alter_role)

    op.execute("DO $$ BEGIN EXECUTE format('GRANT CONNECT ON DATABASE %I TO admin_runtime', current_database()); END $$;")
    op.execute("GRANT USAGE ON SCHEMA public TO admin_runtime")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO admin_runtime")
    op.execute("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO admin_runtime")
    op.execute("ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO admin_runtime")
    op.execute("ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO admin_runtime")

    op.execute("REVOKE ALL PRIVILEGES ON TABLE audit_logs FROM admin_runtime")
    op.execute("GRANT SELECT, INSERT ON TABLE audit_logs TO admin_runtime")
    op.execute("REVOKE ALL PRIVILEGES ON TABLE audit_chain_heads FROM admin_runtime")
    op.execute("GRANT SELECT, UPDATE ON TABLE audit_chain_heads TO admin_runtime")
    op.execute("REVOKE ALL PRIVILEGES ON TABLE alembic_version FROM admin_runtime")


def downgrade() -> None:
    # Keep the non-superuser role and grants so rolling back application code cannot
    # accidentally restore the previous superuser runtime connection.
    pass
