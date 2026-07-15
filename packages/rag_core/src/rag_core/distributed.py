from __future__ import annotations

import asyncio
import time
import uuid
from collections import defaultdict, deque
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class RateLimitResult:
    allowed: bool
    remaining: int
    retry_after_seconds: int


class InMemorySessionStore:
    def __init__(self) -> None:
        self.sessions: dict[str, list[dict[str, str]]] = {}

    async def get_history(self, session_id: str, limit: int = 20) -> list[dict[str, str]]:
        return list(self.sessions.get(session_id, []))[-limit:]

    async def append_message(
        self,
        session_id: str,
        role: str,
        content: str,
        ttl_seconds: int = 86400,
    ) -> None:
        history = self.sessions.setdefault(session_id, [])
        history.append({"role": role, "content": content})

    async def clear(self, session_id: str) -> None:
        self.sessions.pop(session_id, None)


class InMemoryLockManager:
    def __init__(self) -> None:
        self.locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

    @asynccontextmanager
    async def lock(
        self,
        name: str,
        ttl_seconds: int = 120,
        wait_timeout_seconds: float = 0.0,
    ) -> AsyncIterator[str]:
        lock = self.locks[name]
        try:
            await asyncio.wait_for(lock.acquire(), timeout=max(wait_timeout_seconds, 0.001))
        except TimeoutError as error:
            raise RuntimeError(f"Lock is already held: {name}") from error
        token = uuid.uuid4().hex
        try:
            yield token
        finally:
            lock.release()


class InMemoryRateLimiter:
    def __init__(self) -> None:
        self.events: dict[str, deque[float]] = defaultdict(deque)
        self.lock = asyncio.Lock()

    async def check(self, key: str, limit: int, window_seconds: int) -> RateLimitResult:
        now = time.monotonic()
        threshold = now - window_seconds
        async with self.lock:
            events = self.events[key]
            while events and events[0] <= threshold:
                events.popleft()
            if len(events) >= limit:
                retry_after = max(1, int(window_seconds - (now - events[0])))
                return RateLimitResult(False, 0, retry_after)
            events.append(now)
            return RateLimitResult(True, max(limit - len(events), 0), 0)


class RedisSessionStore:
    def __init__(self, client: Any, prefix: str = "rag:session") -> None:
        self.client = client
        self.prefix = prefix

    async def get_history(self, session_id: str, limit: int = 20) -> list[dict[str, str]]:
        import json

        values = await self.client.lrange(self._key(session_id), -limit, -1)
        return [json.loads(value) for value in values]

    async def append_message(
        self,
        session_id: str,
        role: str,
        content: str,
        ttl_seconds: int = 86400,
    ) -> None:
        import json

        key = self._key(session_id)
        pipeline = self.client.pipeline(transaction=True)
        pipeline.rpush(key, json.dumps({"role": role, "content": content}, ensure_ascii=False))
        pipeline.ltrim(key, -100, -1)
        pipeline.expire(key, ttl_seconds)
        await pipeline.execute()

    async def clear(self, session_id: str) -> None:
        await self.client.delete(self._key(session_id))

    def _key(self, session_id: str) -> str:
        return f"{self.prefix}:{session_id}:history"


class RedisLockManager:
    RELEASE_SCRIPT = """
    if redis.call('get', KEYS[1]) == ARGV[1] then
      return redis.call('del', KEYS[1])
    end
    return 0
    """
    EXTEND_SCRIPT = """
    if redis.call('get', KEYS[1]) == ARGV[1] then
      return redis.call('expire', KEYS[1], ARGV[2])
    end
    return 0
    """

    def __init__(self, client: Any, prefix: str = "rag:lock") -> None:
        self.client = client
        self.prefix = prefix

    @asynccontextmanager
    async def lock(
        self,
        name: str,
        ttl_seconds: int = 120,
        wait_timeout_seconds: float = 0.0,
    ) -> AsyncIterator[str]:
        key = f"{self.prefix}:{name}"
        token = uuid.uuid4().hex
        deadline = time.monotonic() + wait_timeout_seconds
        while True:
            acquired = await self.client.set(key, token, nx=True, ex=ttl_seconds)
            if acquired:
                break
            if time.monotonic() >= deadline:
                raise RuntimeError(f"Lock is already held: {name}")
            await asyncio.sleep(0.1)
        renewal = asyncio.create_task(self._renew(key, token, ttl_seconds))
        try:
            yield token
        finally:
            renewal.cancel()
            try:
                await renewal
            except asyncio.CancelledError:
                pass
            await self.client.eval(self.RELEASE_SCRIPT, 1, key, token)

    async def _renew(self, key: str, token: str, ttl_seconds: int) -> None:
        interval = max(ttl_seconds / 3, 1.0)
        while True:
            await asyncio.sleep(interval)
            extended = await self.client.eval(
                self.EXTEND_SCRIPT,
                1,
                key,
                token,
                ttl_seconds,
            )
            if not extended:
                return


class RedisRateLimiter:
    SLIDING_WINDOW_SCRIPT = """
    local key = KEYS[1]
    local now = tonumber(ARGV[1])
    local window = tonumber(ARGV[2])
    local limit = tonumber(ARGV[3])
    local member = ARGV[4]
    redis.call('ZREMRANGEBYSCORE', key, 0, now - window)
    local count = redis.call('ZCARD', key)
    if count >= limit then
      local oldest = redis.call('ZRANGE', key, 0, 0, 'WITHSCORES')
      local retry = window
      if oldest[2] then retry = math.max(1, window - (now - tonumber(oldest[2]))) end
      redis.call('PEXPIRE', key, window)
      return {0, 0, retry}
    end
    redis.call('ZADD', key, now, member)
    redis.call('PEXPIRE', key, window)
    return {1, limit - count - 1, 0}
    """

    def __init__(self, client: Any, prefix: str = "rag:rate") -> None:
        self.client = client
        self.prefix = prefix

    async def check(self, key: str, limit: int, window_seconds: int) -> RateLimitResult:
        now_ms = int(time.time() * 1000)
        result = await self.client.eval(
            self.SLIDING_WINDOW_SCRIPT,
            1,
            f"{self.prefix}:{key}",
            now_ms,
            window_seconds * 1000,
            limit,
            f"{now_ms}:{uuid.uuid4().hex}",
        )
        return RateLimitResult(
            allowed=bool(result[0]),
            remaining=int(result[1]),
            retry_after_seconds=max(1, int(result[2] / 1000)) if result[2] else 0,
        )
