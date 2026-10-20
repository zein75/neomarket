import asyncio
import json

from src.core.database import AsyncSessionLocal
from src.services.audit_integrity import verify_audit_chain


async def main() -> None:
    async with AsyncSessionLocal() as session:
        result = await verify_audit_chain(session)
    print(json.dumps({"status": "VALID", **result}, sort_keys=True))


if __name__ == "__main__":
    asyncio.run(main())
