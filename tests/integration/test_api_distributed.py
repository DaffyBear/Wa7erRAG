from pathlib import Path

from app.core.config import get_settings
from app.core.container import get_container
from app.main import app
from fastapi.testclient import TestClient


def test_chat_rate_limit_and_session_endpoints(tmp_path: Path) -> None:
    settings = get_settings()
    original_limit = settings.rag_chat_rate_limit
    settings.rag_chat_rate_limit = 2
    container = get_container()
    source = tmp_path / "guide.md"
    source.write_text("# MQTT\n\n默认端口是1883。", encoding="utf-8")

    with TestClient(app) as client:
        import asyncio

        asyncio.run(container.ingestion.ingest_path(source, force=True))
        headers = {"x-user-id": "rate-test-user"}
        first = client.post("/api/v1/chat", json={"query": "MQTT端口？"}, headers=headers)
        second = client.post("/api/v1/chat", json={"query": "MQTT端口？"}, headers=headers)
        third = client.post("/api/v1/chat", json={"query": "MQTT端口？"}, headers=headers)
        assert first.status_code == second.status_code == 200
        assert first.headers["x-ratelimit-limit"] == "2"
        assert third.status_code == 429
        assert "retry-after" in third.headers

        session_id = first.json()["session_id"]
        history = client.get(f"/api/v1/chat/sessions/{session_id}")
        assert history.status_code == 200
        assert len(history.json()["history"]) == 2
        cleared = client.delete(f"/api/v1/chat/sessions/{session_id}")
        assert cleared.status_code == 204
        assert client.get(f"/api/v1/chat/sessions/{session_id}").json()["history"] == []

    settings.rag_chat_rate_limit = original_limit
