from __future__ import annotations

from typing import Any

from rag_core.distributed import RedisLockManager, RedisRateLimiter, RedisSessionStore


class RedisStateBackend:
    def __init__(self, url: str) -> None:
        from redis.asyncio import from_url

        self.client: Any = from_url(url, decode_responses=True)
        self.sessions = RedisSessionStore(self.client)
        self.locks = RedisLockManager(self.client)
        self.rate_limiter = RedisRateLimiter(self.client)

    async def ping(self) -> bool:
        return bool(await self.client.ping())

    async def close(self) -> None:
        await self.client.aclose()
