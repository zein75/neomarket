# Admin PostgreSQL integration rerun — 2026-10-20

- Run ID: dmin-full-postgres-2026-10-20
- Source checkout: $sha
- Environment: local disposable PostgreSQL 16 only; no staging or production data
- Migration: uv run --frozen alembic upgrade head — PASS
- Integration command: uv run --frozen pytest -m postgres_integration -q — **63 passed, 2 skipped, 58 deselected, 1 warning**
- Container cleanup: completed by the existing runner after the test
- Authenticated Keycloak/browser evidence: not part of this run

The two skipped tests require separate Redis/B2B prerequisites. This run is backend evidence only; it does not close the external contract or authenticated browser gates in the current acceptance matrix.
