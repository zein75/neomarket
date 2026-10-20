# Staging rollback

Rollback is an explicit owner/deployment operation. It is not an automatic
database downgrade and never removes Docker volumes.

1. Identify the last successful SHA from `/opt/neomarket-staging/last-successful-sha` and the target immutable image SHA.
2. Submit the target SHA through the forced `neomarket-staging-request <sha>` command.
3. Let the root-owned wrapper run backward-compatible migrations, readiness and smoke checks.
4. If the release is not backward compatible, stop and restore the database into an isolated environment first. Do not run `docker compose down -v` or an automatic Alembic downgrade.
5. Record the incident, deployment log, image digests and database restore evidence in `docs/automation/`.
