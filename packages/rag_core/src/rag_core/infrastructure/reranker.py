from __future__ import annotations

from collections.abc import Sequence

import httpx

from rag_core.models import RetrievalResult


class HttpReranker:
    def __init__(
        self,
        endpoint: str,
        model: str,
        api_key: str = "",
        timeout: float = 30.0,
    ) -> None:
        self.endpoint = endpoint
        self.model = model
        self.api_key = api_key
        self.timeout = timeout

    async def rerank(
        self, query: str, candidates: Sequence[RetrievalResult]
    ) -> list[RetrievalResult]:
        if not candidates:
            return []
        payload = {
            "model": self.model,
            "query": query,
            "documents": [item.content for item in candidates],
            "top_n": len(candidates),
            "return_documents": False,
        }
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(self.endpoint, headers=headers, json=payload)
            response.raise_for_status()
        ranked = response.json().get("results", [])
        if len(ranked) != len(candidates):
            raise ValueError("Reranker returned an unexpected number of results")
        results: list[RetrievalResult] = []
        for item in ranked:
            index = int(item["index"])
            if index < 0 or index >= len(candidates):
                raise ValueError("Reranker returned an invalid document index")
            candidate = candidates[index]
            candidate.score = float(item["relevance_score"])
            results.append(candidate)
        return results
