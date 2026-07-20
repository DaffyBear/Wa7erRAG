from datetime import UTC, datetime, timedelta

import pytest
from rag_core.infrastructure import InMemoryTraceRepository
from rag_core.models import MessageTrace


def trace(
    message_id: str,
    session_id: str,
    query: str,
    *,
    tenant_id: str = "default",
    user_id: str = "user-1",
    offset: int = 0,
) -> MessageTrace:
    return MessageTrace(
        message_id=message_id,
        session_id=session_id,
        query=query,
        rewritten_query=query,
        answer=f"answer:{query}",
        retrieved_documents=[],
        timings_ms={"total": 1.0},
        tenant_id=tenant_id,
        user_id=user_id,
        created_at=datetime(2026, 7, 20, tzinfo=UTC) + timedelta(seconds=offset),
    )


@pytest.mark.asyncio
async def test_session_repository_lists_restores_renames_and_deletes() -> None:
    repository = InMemoryTraceRepository()
    await repository.save_message(trace("m1", "s1", "First question", offset=1))
    await repository.save_message(trace("m2", "s1", "Second question", offset=2))
    await repository.save_message(trace("m3", "s2", "Latest chat", offset=3))
    await repository.save_message(
        trace("m4", "other", "Other tenant", tenant_id="tenant-2", offset=4)
    )

    sessions = await repository.list_sessions("default", "user-1")

    assert [item.session_id for item in sessions] == ["s2", "s1"]
    assert sessions[1].title == "First question"
    assert sessions[1].message_count == 2
    assert [item.message_id for item in await repository.get_session_messages(
        "s1", "default", "user-1"
    )] == ["m1", "m2"]

    renamed = await repository.rename_session("s1", "Renamed", "default", "user-1")
    assert renamed is not None
    assert renamed.title == "Renamed"

    assert await repository.delete_session("s1", "default", "user-1")
    assert await repository.get_session_messages("s1", "default", "user-1") == []
    assert not await repository.delete_session("s1", "default", "user-1")