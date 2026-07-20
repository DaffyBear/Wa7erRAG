from __future__ import annotations

import json

import httpx
import pytest
from rag_core.models import RetrievalDecision
from rag_core.retrieval.router import (
    OpenAICompatibleRetrievalRouter,
    deterministic_retrieval_decision,
    parse_retrieval_decision,
)


def test_deterministic_router_handles_clear_routes() -> None:
    assert deterministic_retrieval_decision("你好") is False
    assert deterministic_retrieval_decision("你是什么模型？") is False
    assert deterministic_retrieval_decision("根据知识库说明MQTT配置") is True
    assert deterministic_retrieval_decision("E_CONN_1042是什么错误？") is True
    assert deterministic_retrieval_decision("如何提高系统稳定性？") is None


def test_router_parser_accepts_only_strict_boolean_json() -> None:
    assert parse_retrieval_decision('{"needs_retrieval":true}') is True
    assert parse_retrieval_decision('```json\n{"needs_retrieval": false}\n```') is False

    with pytest.raises(ValueError):
        parse_retrieval_decision('{"needs_retrieval":"yes"}')
    with pytest.raises(ValueError):
        parse_retrieval_decision('{"needs_retrieval":true,"reason":"x"}')
    with pytest.raises(ValueError):
        parse_retrieval_decision("需要检索")


@pytest.mark.asyncio
async def test_openai_router_uses_model_for_uncertain_query(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": '{"needs_retrieval":true}'}}]},
        )

    original_async_client = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: original_async_client(transport=httpx.MockTransport(handler), **kwargs),
    )
    router = OpenAICompatibleRetrievalRouter(
        "https://router.example/v1", "secret", "deepseek-v4-flash"
    )

    decision = await router.decide("如何提高系统稳定性？")

    assert decision == RetrievalDecision(True, "model")
    assert captured["model"] == "deepseek-v4-flash"
    assert captured["temperature"] == 0
    assert captured["max_tokens"] == 256
    assert captured["response_format"] == {"type": "json_object"}
