from __future__ import annotations

from collections.abc import Sequence

import httpx

from rag_core.models import RetrievalResult


class HttpReranker:
    def __init__(self, endpoint: str, model: str, timeout: float = 30.0) -> None:
        self.endpoint = endpoint
        self.model = model
        self.timeout = timeout

    async def rerank(
        self, query: str, candidates: Sequence[RetrievalResult]
    ) -> list[RetrievalResult]:
        payload = {
            "model": self.model,
            "query": query,
            "documents": [item.content for item in candidates],
        }
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(self.endpoint, json=payload)
            response.raise_for_status()
        scores = response.json().get("scores", [])
        if len(scores) != len(candidates):
            raise ValueError("Reranker returned an unexpected number of scores")
        results = list(candidates)
        for result, score in zip(results, scores, strict=True):
            result.score = float(score)
        return sorted(results, key=lambda item: item.score, reverse=True)
