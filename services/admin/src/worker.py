import asyncio
import signal

from src.workers.outbox import moderation_outbox_worker


async def main() -> None:
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(signum, stop.set)
    await moderation_outbox_worker(stop)


if __name__ == "__main__":
    asyncio.run(main())
