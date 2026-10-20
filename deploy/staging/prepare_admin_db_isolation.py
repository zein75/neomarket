"""Safely copy legacy Admin staging data to the isolated Admin PostgreSQL instance."""

import argparse
import os
from pathlib import Path
import subprocess
from datetime import datetime, timezone


STATE_ROOT = Path("/opt/neomarket-staging")
ROOT = STATE_ROOT / "compose"
SECRETS = Path("/etc/neomarket/staging.env")
MARKER = STATE_ROOT / ".admin-db-isolated"
LIVE_MARKER = STATE_ROOT / ".admin-db-live"
BACKUPS = STATE_ROOT / "backups"
COMPOSE = [
    "docker", "compose", "--project-name", "neomarket-staging",
    "--env-file", str(SECRETS), "--env-file", str(STATE_ROOT / ".release.env"),
    "-f", str(ROOT / "docker-compose.staging.yml"),
]


def table_count(service: str) -> int:
    result = subprocess.run(
        [*COMPOSE, "exec", "-T", service, "psql", "-U",
         "neomarket" if service == "postgres" else "admin_owner",
         "-d", "admin", "-Atqc", "SELECT count(*) FROM pg_tables WHERE schemaname='public'"],
        check=True, capture_output=True, text=True,
    )
    return int(result.stdout.strip())


def ensure_copy() -> None:
    source_count = table_count("postgres")
    target_count = table_count("admin-postgres")
    if LIVE_MARKER.exists() and target_count == 0:
        raise SystemExit("Admin DB was previously deployed but is now empty; refusing to initialize over lost data")
    if MARKER.exists():
        if target_count == 0 and source_count > 0:
            raise SystemExit("Isolation marker exists but target Admin DB is empty; refusing automatic recovery")
        return
    if source_count == 0:
        if target_count > 0:
            raise SystemExit("Target Admin DB is populated without an isolation marker; investigate before deploy")
        MARKER.touch()
        return
    raise SystemExit(
        "Legacy shared Admin DB contains tables. Run prepare_admin_db_isolation.py "
        "--copy --confirm-staging-admin-db-copy after reviewing the staging backup."
    )


def copy_legacy_data() -> None:
    if MARKER.exists():
        raise SystemExit("Admin DB isolation marker already exists; refusing a second copy")
    source_count = table_count("postgres")
    target_count = table_count("admin-postgres")
    if source_count == 0:
        raise SystemExit("Legacy Admin DB is empty; no copy is needed")
    if target_count != 0:
        raise SystemExit("Isolated Admin DB is not empty; refusing to overwrite it")

    BACKUPS.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(BACKUPS, 0o700)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = BACKUPS / f"admin-pre-isolation-{stamp}.dump.enc"
    backup_password = next((
        line.split("=", 1)[1].strip()
        for line in SECRETS.read_text(encoding="utf-8").splitlines()
        if line.startswith("ADMIN_DB_BACKUP_PASSWORD=")
    ), "")
    if len(backup_password) < 32:
        raise SystemExit("ADMIN_DB_BACKUP_PASSWORD is missing or too short")
    crypto_env = {**os.environ, "ADMIN_DB_BACKUP_PASSWORD": backup_password}
    fd = os.open(backup, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    backup_complete = False
    try:
        with os.fdopen(fd, "wb") as stream:
            dump = subprocess.Popen(
                [*COMPOSE, "exec", "-T", "postgres", "pg_dump", "-U", "neomarket", "-d", "admin", "-Fc"],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            )
            encrypt = subprocess.Popen(
                ["openssl", "enc", "-aes-256-cbc", "-pbkdf2", "-salt", "-pass", "env:ADMIN_DB_BACKUP_PASSWORD"],
                stdin=dump.stdout, stdout=stream, stderr=subprocess.PIPE, env=crypto_env,
            )
            assert dump.stdout is not None
            dump.stdout.close()
            _, encrypt_error = encrypt.communicate()
            dump_status = dump.wait()
            if encrypt.returncode != 0 or dump_status != 0:
                raise RuntimeError(f"Encrypted staging dump failed (dump={dump_status}, crypto={encrypt.returncode}): {encrypt_error.decode(errors='replace')}")
            stream.flush()
            os.fsync(stream.fileno())
            backup_complete = True

        with backup.open("rb") as encrypted_file:
            decrypt = subprocess.Popen(
                ["openssl", "enc", "-d", "-aes-256-cbc", "-pbkdf2", "-pass", "env:ADMIN_DB_BACKUP_PASSWORD"],
                stdin=encrypted_file, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=crypto_env,
            )
            restore = subprocess.Popen(
                [*COMPOSE, "exec", "-T", "admin-postgres", "pg_restore", "-U", "admin_owner", "-d", "admin",
                 "--no-owner", "--no-privileges", "--clean", "--if-exists", "--exit-on-error"],
                stdin=decrypt.stdout, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
            )
            assert decrypt.stdout is not None
            decrypt.stdout.close()
            _, restore_error = restore.communicate()
            _, decrypt_error = decrypt.communicate()
            if restore.returncode != 0 or decrypt.returncode != 0:
                raise RuntimeError(
                    f"Admin DB restore failed (decrypt={decrypt.returncode}, restore={restore.returncode}): "
                    f"{restore_error.decode(errors='replace')} {decrypt_error.decode(errors='replace')}"
                )
    except Exception:
        if not backup_complete:
            backup.unlink(missing_ok=True)
        raise
    if table_count("admin-postgres") == 0:
        raise SystemExit(f"Restore produced no public tables; preserve backup at {backup} and investigate")
    MARKER.touch()
    print(f"Admin staging data copied; source retained; encrypted/offsite backup still required: {backup}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--copy", action="store_true", help="copy legacy staging Admin data once")
    parser.add_argument("--confirm-staging-admin-db-copy", action="store_true", help="acknowledge this is a staging-only copy")
    args = parser.parse_args()
    subprocess.run([*COMPOSE, "up", "-d", "--wait", "postgres", "admin-postgres"], check=True)
    if args.copy:
        if not args.confirm_staging_admin_db_copy:
            raise SystemExit("--copy requires --confirm-staging-admin-db-copy")
        copy_legacy_data()
    else:
        ensure_copy()


if __name__ == "__main__":
    main()
