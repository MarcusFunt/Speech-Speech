from __future__ import annotations

import asyncio

from local_assistant.server import health


async def _main() -> None:
    result = await health()
    print(result)


if __name__ == "__main__":
    asyncio.run(_main())
