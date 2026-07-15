from __future__ import annotations

import json
from typing import Any


class InMemoryCache:
    def __init__(self) -> None:
        self.values: dict[str, Any] = {}

    async def get_json(self, key: str) -> Any | None:
        return self.values.get(key)

    async def set_json(self, key: str, value: Any, ttl_seconds: int = 300) -> None:
        self.values[key] = value


class RedisCache:
    def __init__(self, url: str) -> None:
        from redis.asyncio import from_url

        self.client = from_url(url, decode_responses=True)

    async def get_json(self, key: str) -> Any | None:
        value = await self.client.get(key)
        return json.loads(value) if value else None

    async def set_json(self, key: str, value: Any, ttl_seconds: int = 300) -> None:
        await self.client.set(key, json.dumps(value, ensure_ascii=False), ex=ttl_seconds)
