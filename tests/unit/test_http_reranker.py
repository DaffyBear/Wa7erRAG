import pytest
from rag_core.infrastructure.reranker import HttpReranker
from rag_core.models import RetrievalResult


class FakeResponse:
    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, object]:
        return {
            "results": [
                {"index": 1, "relevance_score": 0.95},
                {"index": 0, "relevance_score": 0.12},
            ]
        }


class FakeAsyncClient:
    last_headers: dict[str, str] = {}
    last_payload: dict[str, object] = {}

    def __init__(self, timeout: float) -> None:
        self.timeout = timeout

    async def __aenter__(self) -> "FakeAsyncClient":
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def post(
        self,
        endpoint: str,
        headers: dict[str, str],
        json: dict[str, object],
    ) -> FakeResponse:
        assert endpoint == "https://api.example.com/v1/rerank"
        type(self).last_headers = headers
        type(self).last_payload = json
        return FakeResponse()


@pytest.mark.asyncio
async def test_http_reranker_supports_siliconflow_response(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("rag_core.infrastructure.reranker.httpx.AsyncClient", FakeAsyncClient)
    reranker = HttpReranker(
        "https://api.example.com/v1/rerank",
        "BAAI/bge-reranker-v2-m3",
        "secret-key",
    )
    candidates = [
        RetrievalResult("first", "first.md", "unrelated", 0.0),
        RetrievalResult("second", "second.md", "relevant", 0.0),
    ]

    results = await reranker.rerank("query", candidates)

    assert [item.document_id for item in results] == ["second", "first"]
    assert [item.score for item in results] == [0.95, 0.12]
    assert FakeAsyncClient.last_headers == {"Authorization": "Bearer secret-key"}
    assert FakeAsyncClient.last_payload == {
        "model": "BAAI/bge-reranker-v2-m3",
        "query": "query",
        "documents": ["unrelated", "relevant"],
        "top_n": 2,
        "return_documents": False,
    }
