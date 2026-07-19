from __future__ import annotations

import asyncio
import logging
import math
import random
import time
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import replace
from email.utils import parsedate_to_datetime
from typing import Any

import httpx

from rag_core.contracts import Reranker
from rag_core.metrics import (
    RERANK_CANDIDATES,
    RERANK_CIRCUIT_STATE,
    RERANK_LATENCY,
    RERANK_OPERATIONS,
)
from rag_core.models import RetrievalResult

logger = logging.getLogger(__name__)

_RETRYABLE_STATUS_CODES = {408, 425, 429, 500, 502, 503, 504}
_CIRCUIT_CLOSED = 0
_CIRCUIT_OPEN = 1
_CIRCUIT_HALF_OPEN = 2


class HttpReranker:
    def __init__(
        self,
        endpoint: str,
        model: str,
        api_key: str = "",
        timeout: float = 10.0,
        max_retries: int = 2,
        retry_base_delay_seconds: float = 0.25,
        retry_max_delay_seconds: float = 2.0,
        max_concurrency: int = 8,
        queue_timeout_seconds: float = 2.0,
        circuit_failure_threshold: int = 5,
        circuit_recovery_seconds: float = 30.0,
        max_document_chars: int = 12000,
        fallback: Reranker | None = None,
        client: httpx.AsyncClient | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        if max_retries < 0:
            raise ValueError("max_retries must be non-negative")
        if max_concurrency < 1:
            raise ValueError("max_concurrency must be positive")
        if circuit_failure_threshold < 1:
            raise ValueError("circuit_failure_threshold must be positive")
        if max_document_chars < 1:
            raise ValueError("max_document_chars must be positive")
        self.endpoint = endpoint
        self.model = model
        self.api_key = api_key
        self.timeout = timeout
        self.max_retries = max_retries
        self.retry_base_delay_seconds = retry_base_delay_seconds
        self.retry_max_delay_seconds = retry_max_delay_seconds
        self.queue_timeout_seconds = queue_timeout_seconds
        self.circuit_failure_threshold = circuit_failure_threshold
        self.circuit_recovery_seconds = circuit_recovery_seconds
        self.max_document_chars = max_document_chars
        self.fallback = fallback
        self._client = client or httpx.AsyncClient(
            timeout=httpx.Timeout(timeout),
            limits=httpx.Limits(
                max_connections=max_concurrency,
                max_keepalive_connections=max_concurrency,
            ),
        )
        self._owns_client = client is None
        self._semaphore = asyncio.Semaphore(max_concurrency)
        self._state_lock = asyncio.Lock()
        self._failure_count = 0
        self._opened_at: float | None = None
        self._half_open_in_flight = False
        self._clock = clock
        self._sleep = sleep
        RERANK_CIRCUIT_STATE.set(_CIRCUIT_CLOSED)

    async def rerank(
        self, query: str, candidates: Sequence[RetrievalResult]
    ) -> list[RetrievalResult]:
        if not candidates:
            return []
        safe_candidates = [_copy_result(item) for item in candidates]
        RERANK_CANDIDATES.observe(len(safe_candidates))

        if not await self._allow_remote_request():
            RERANK_OPERATIONS.labels(outcome="circuit_open").inc()
            return await self._fallback(query, safe_candidates, "circuit_open")

        acquired = False
        started = self._clock()
        try:
            await asyncio.wait_for(
                self._semaphore.acquire(),
                timeout=self.queue_timeout_seconds,
            )
            acquired = True
        except TimeoutError:
            await self._release_half_open_probe()
            RERANK_OPERATIONS.labels(outcome="queue_timeout").inc()
            return await self._fallback(query, safe_candidates, "queue_timeout")

        try:
            ranked = await self._request_with_retries(query, safe_candidates)
        except Exception as error:
            await self._record_failure()
            RERANK_OPERATIONS.labels(outcome="failure").inc()
            RERANK_LATENCY.labels(provider="remote", outcome="failure").observe(
                max(self._clock() - started, 0.0)
            )
            logger.warning(
                "Remote rerank failed; using fallback",
                extra={
                    "reason": _failure_reason(error),
                    "model": self.model,
                    "endpoint": self.endpoint,
                },
            )
            logger.debug("Remote rerank failure details", exc_info=True)
            return await self._fallback(
                query,
                safe_candidates,
                _failure_reason(error),
            )
        else:
            await self._record_success()
            RERANK_OPERATIONS.labels(outcome="success").inc()
            RERANK_LATENCY.labels(provider="remote", outcome="success").observe(
                max(self._clock() - started, 0.0)
            )
            return ranked
        finally:
            if acquired:
                self._semaphore.release()

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def _request_with_retries(
        self,
        query: str,
        candidates: Sequence[RetrievalResult],
    ) -> list[RetrievalResult]:
        payload = {
            "model": self.model,
            "query": query,
            "documents": [item.content[: self.max_document_chars] for item in candidates],
            "top_n": len(candidates),
            "return_documents": False,
        }
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                response = await self._client.post(self.endpoint, headers=headers, json=payload)
                if response.status_code in _RETRYABLE_STATUS_CODES:
                    raise _RetryableHttpStatus(response)
                response.raise_for_status()
                return _parse_results(response.json(), candidates, self.model)
            except Exception as error:
                last_error = error
                if attempt >= self.max_retries or not _is_retryable(error):
                    raise
                RERANK_OPERATIONS.labels(outcome="retry").inc()
                delay = _retry_delay(
                    error,
                    attempt,
                    self.retry_base_delay_seconds,
                    self.retry_max_delay_seconds,
                )
                await self._sleep(delay)
        assert last_error is not None
        raise last_error

    async def _allow_remote_request(self) -> bool:
        async with self._state_lock:
            if self._opened_at is None:
                return True
            if self._clock() - self._opened_at < self.circuit_recovery_seconds:
                return False
            if self._half_open_in_flight:
                return False
            self._half_open_in_flight = True
            RERANK_CIRCUIT_STATE.set(_CIRCUIT_HALF_OPEN)
            return True

    async def _record_success(self) -> None:
        async with self._state_lock:
            self._failure_count = 0
            self._opened_at = None
            self._half_open_in_flight = False
            RERANK_CIRCUIT_STATE.set(_CIRCUIT_CLOSED)

    async def _record_failure(self) -> None:
        async with self._state_lock:
            self._failure_count += 1
            should_open = (
                self._half_open_in_flight
                or self._failure_count >= self.circuit_failure_threshold
            )
            self._half_open_in_flight = False
            if should_open:
                self._opened_at = self._clock()
                RERANK_CIRCUIT_STATE.set(_CIRCUIT_OPEN)

    async def _release_half_open_probe(self) -> None:
        async with self._state_lock:
            self._half_open_in_flight = False
            if self._opened_at is not None:
                RERANK_CIRCUIT_STATE.set(_CIRCUIT_OPEN)

    async def _fallback(
        self,
        query: str,
        candidates: list[RetrievalResult],
        reason: str,
    ) -> list[RetrievalResult]:
        if self.fallback is None:
            raise RuntimeError(f"Rerank service unavailable: {reason}")
        started = self._clock()
        ranked = await self.fallback.rerank(query, candidates)
        for item in ranked:
            item.metadata["rerank_provider"] = "fallback"
            item.metadata["rerank_fallback_reason"] = reason
        RERANK_OPERATIONS.labels(outcome="fallback").inc()
        RERANK_LATENCY.labels(provider="fallback", outcome="success").observe(
            max(self._clock() - started, 0.0)
        )
        return ranked


class _RetryableHttpStatus(httpx.HTTPStatusError):
    def __init__(self, response: httpx.Response) -> None:
        super().__init__(
            f"Retryable rerank status: {response.status_code}",
            request=response.request,
            response=response,
        )


def _parse_results(
    payload: Any,
    candidates: Sequence[RetrievalResult],
    model: str,
) -> list[RetrievalResult]:
    if not isinstance(payload, dict) or not isinstance(payload.get("results"), list):
        raise ValueError("Reranker response must contain a results list")
    raw_results = payload["results"]
    if len(raw_results) != len(candidates):
        raise ValueError("Reranker returned an unexpected number of results")
    ranked: list[RetrievalResult] = []
    seen_indices: set[int] = set()
    for item in raw_results:
        if not isinstance(item, dict):
            raise ValueError("Reranker result must be an object")
        index = int(item["index"])
        score = float(item["relevance_score"])
        if index < 0 or index >= len(candidates) or index in seen_indices:
            raise ValueError("Reranker returned an invalid document index")
        if not math.isfinite(score):
            raise ValueError("Reranker returned a non-finite score")
        seen_indices.add(index)
        candidate = _copy_result(candidates[index])
        candidate.score = score
        candidate.metadata["rerank_provider"] = "remote"
        candidate.metadata["rerank_model"] = str(payload.get("model", "")) or model
        ranked.append(candidate)
    return ranked


def _copy_result(item: RetrievalResult) -> RetrievalResult:
    return replace(item, chunks=list(item.chunks), metadata=dict(item.metadata))


def _is_retryable(error: Exception) -> bool:
    return isinstance(
        error,
        (
            _RetryableHttpStatus,
            httpx.TimeoutException,
            httpx.NetworkError,
            httpx.RemoteProtocolError,
        ),
    )


def _retry_delay(
    error: Exception,
    attempt: int,
    base_delay: float,
    max_delay: float,
) -> float:
    retry_after = _retry_after_seconds(error)
    if retry_after is not None:
        return min(max(retry_after, 0.0), max_delay)
    exponential = min(base_delay * (2**attempt), max_delay)
    return min(exponential * random.uniform(0.8, 1.2), max_delay)


def _retry_after_seconds(error: Exception) -> float | None:
    if not isinstance(error, httpx.HTTPStatusError):
        return None
    value = error.response.headers.get("retry-after")
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        try:
            retry_at = parsedate_to_datetime(value)
            return max(retry_at.timestamp() - time.time(), 0.0)
        except (TypeError, ValueError, OverflowError):
            return None


def _failure_reason(error: Exception) -> str:
    if isinstance(error, httpx.TimeoutException):
        return "timeout"
    if isinstance(error, httpx.NetworkError):
        return "network_error"
    if isinstance(error, httpx.HTTPStatusError):
        return f"http_{error.response.status_code}"
    if isinstance(error, ValueError):
        return "invalid_response"
    return "unexpected_error"
