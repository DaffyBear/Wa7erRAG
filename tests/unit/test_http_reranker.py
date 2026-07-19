from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

import httpx
import pytest
from rag_core.infrastructure.reranker import HttpReranker
from rag_core.models import RetrievalResult
from rag_core.retrieval import LexicalReranker


def candidates() -> list[RetrievalResult]:
    return [
        RetrievalResult("first", "first.md", "unrelated weather content", 0.8),
        RetrievalResult("second", "second.md", "MQTT default port is 1883", 0.7),
    ]


def success_response(request: httpx.Request) -> httpx.Response:
    return httpx.Response(
        200,
        request=request,
        json={
            "model": "BAAI/bge-reranker-v2-m3",
            "results": [
                {"index": 1, "relevance_score": 0.95},
                {"index": 0, "relevance_score": 0.12},
            ],
        },
    )


def client_for(
    handler: Callable[[httpx.Request], httpx.Response | Awaitable[httpx.Response]],
) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


@pytest.mark.asyncio
async def test_http_reranker_supports_siliconflow_response_and_truncation() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["authorization"] = request.headers.get("authorization")
        captured["payload"] = request.read().decode()
        return success_response(request)

    client = client_for(handler)
    reranker = HttpReranker(
        "https://api.example.com/v1/rerank",
        "BAAI/bge-reranker-v2-m3",
        "secret-key",
        max_document_chars=10,
        client=client,
    )

    results = await reranker.rerank("MQTT port", candidates())

    assert [item.document_id for item in results] == ["second", "first"]
    assert [item.score for item in results] == [0.95, 0.12]
    assert results[0].metadata["rerank_provider"] == "remote"
    assert results[0].metadata["rerank_model"] == "BAAI/bge-reranker-v2-m3"
    assert captured["authorization"] == "Bearer secret-key"
    assert '"top_n":2' in str(captured["payload"]).replace(" ", "")
    assert "unrelated " in str(captured["payload"])
    await client.aclose()


@pytest.mark.asyncio
async def test_http_reranker_retries_retryable_status() -> None:
    attempts = 0
    delays: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(429, request=request, headers={"retry-after": "0.5"})
        return success_response(request)

    async def record_sleep(delay: float) -> None:
        delays.append(delay)

    client = client_for(handler)
    reranker = HttpReranker(
        "https://api.example.com/v1/rerank",
        "model",
        max_retries=1,
        retry_max_delay_seconds=1.0,
        client=client,
        sleep=record_sleep,
    )

    results = await reranker.rerank("MQTT", candidates())

    assert attempts == 2
    assert delays == [0.5]
    assert results[0].document_id == "second"
    await client.aclose()


@pytest.mark.asyncio
async def test_http_reranker_falls_back_on_non_retryable_error() -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(401, request=request)

    client = client_for(handler)
    reranker = HttpReranker(
        "https://api.example.com/v1/rerank",
        "model",
        max_retries=3,
        fallback=LexicalReranker(),
        client=client,
    )

    results = await reranker.rerank("MQTT", candidates())

    assert attempts == 1
    assert all(item.metadata["rerank_provider"] == "fallback" for item in results)
    assert all(item.metadata["rerank_fallback_reason"] == "http_401" for item in results)
    await client.aclose()


@pytest.mark.asyncio
async def test_http_reranker_opens_and_recovers_circuit() -> None:
    now = 100.0
    attempts = 0
    remote_available = False

    def clock() -> float:
        return now

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if not remote_available:
            raise httpx.ConnectError("offline", request=request)
        return success_response(request)

    client = client_for(handler)
    reranker = HttpReranker(
        "https://api.example.com/v1/rerank",
        "model",
        max_retries=0,
        circuit_failure_threshold=2,
        circuit_recovery_seconds=10,
        fallback=LexicalReranker(),
        client=client,
        clock=clock,
    )

    first = await reranker.rerank("MQTT", candidates())
    second = await reranker.rerank("MQTT", candidates())
    third = await reranker.rerank("MQTT", candidates())

    assert attempts == 2
    assert first[0].metadata["rerank_fallback_reason"] == "network_error"
    assert second[0].metadata["rerank_fallback_reason"] == "network_error"
    assert third[0].metadata["rerank_fallback_reason"] == "circuit_open"

    now += 11
    remote_available = True
    recovered = await reranker.rerank("MQTT", candidates())

    assert attempts == 3
    assert recovered[0].metadata["rerank_provider"] == "remote"
    await client.aclose()


@pytest.mark.asyncio
async def test_http_reranker_queue_timeout_uses_fallback() -> None:
    request_started = asyncio.Event()
    release_request = asyncio.Event()

    async def handler(request: httpx.Request) -> httpx.Response:
        request_started.set()
        await release_request.wait()
        return success_response(request)

    client = client_for(handler)
    reranker = HttpReranker(
        "https://api.example.com/v1/rerank",
        "model",
        max_concurrency=1,
        queue_timeout_seconds=0.01,
        fallback=LexicalReranker(),
        client=client,
    )

    active = asyncio.create_task(reranker.rerank("MQTT", candidates()))
    await request_started.wait()
    queued = await reranker.rerank("MQTT", candidates())
    release_request.set()
    remote = await active

    assert queued[0].metadata["rerank_fallback_reason"] == "queue_timeout"
    assert remote[0].metadata["rerank_provider"] == "remote"
    await client.aclose()


@pytest.mark.asyncio
async def test_http_reranker_invalid_response_uses_fallback_without_mutating_input() -> None:
    original = candidates()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            request=request,
            json={
                "results": [
                    {"index": 0, "relevance_score": 0.9},
                    {"index": 0, "relevance_score": 0.8},
                ]
            },
        )

    client = client_for(handler)
    reranker = HttpReranker(
        "https://api.example.com/v1/rerank",
        "model",
        max_retries=0,
        fallback=LexicalReranker(),
        client=client,
    )

    results = await reranker.rerank("MQTT", original)

    assert results[0].metadata["rerank_fallback_reason"] == "invalid_response"
    assert [item.score for item in original] == [0.8, 0.7]
    assert all(not item.metadata for item in original)
    await client.aclose()


@pytest.mark.asyncio
async def test_http_reranker_empty_candidates_skips_remote_call() -> None:
    async def handler(_: httpx.Request) -> httpx.Response:
        raise AssertionError("remote call should not happen")

    client = client_for(handler)
    reranker = HttpReranker("https://api.example.com/v1/rerank", "model", client=client)

    assert await reranker.rerank("query", []) == []
    await client.aclose()
