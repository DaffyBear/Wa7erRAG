import pytest
from rag_core.distributed import InMemoryLockManager, InMemoryRateLimiter, InMemorySessionStore


@pytest.mark.asyncio
async def test_session_store_retains_recent_messages() -> None:
    store = InMemorySessionStore()
    await store.append_message("s", "user", "问题")
    await store.append_message("s", "assistant", "回答")
    assert await store.get_history("s") == [
        {"role": "user", "content": "问题"},
        {"role": "assistant", "content": "回答"},
    ]
    await store.clear("s")
    assert await store.get_history("s") == []


@pytest.mark.asyncio
async def test_lock_rejects_concurrent_holder() -> None:
    manager = InMemoryLockManager()
    async with manager.lock("job", wait_timeout_seconds=0.01):
        with pytest.raises(RuntimeError):
            async with manager.lock("job", wait_timeout_seconds=0.01):
                pass


@pytest.mark.asyncio
async def test_sliding_window_rate_limiter() -> None:
    limiter = InMemoryRateLimiter()
    assert (await limiter.check("client", 2, 60)).allowed
    assert (await limiter.check("client", 2, 60)).allowed
    rejected = await limiter.check("client", 2, 60)
    assert not rejected.allowed
    assert rejected.retry_after_seconds >= 1
