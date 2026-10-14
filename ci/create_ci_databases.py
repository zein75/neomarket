"""Create isolated CI databases using credentials for the ephemeral postgres service."""
import asyncio
import os
import asyncpg


async def main() -> None:
    for attempt in range(30):
        try:
            conn = await asyncpg.connect(
                user=os.environ["POSTGRES_USER"],
                password=os.environ["POSTGRES_PASSWORD"],
                host=os.environ.get("PGHOST", "localhost"), database="postgres", timeout=3,
            )
            break
        except (ConnectionError, OSError, asyncpg.PostgresError):
            if attempt == 29:
                raise
            await asyncio.sleep(2)
    try:
        for db in ("b2b", "b2c", "admin"):
            await conn.execute(f'CREATE DATABASE "{db}"')
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
