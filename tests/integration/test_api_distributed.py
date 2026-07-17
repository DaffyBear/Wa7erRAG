from pathlib import Path

from app.core.config import get_settings
from app.core.container import get_container
from app.main import app
from fastapi.testclient import TestClient


def test_chat_rate_limit_and_session_endpoints(tmp_path: Path) -> None:
    settings = get_settings()
    original_limit = settings.rag_chat_rate_limit
    original_providers = {
        "rag_metadata_provider": settings.rag_metadata_provider,
        "rag_embedding_provider": settings.rag_embedding_provider,
        "rag_vector_store_provider": settings.rag_vector_store_provider,
        "rag_object_store_provider": settings.rag_object_store_provider,
        "rag_rewrite_provider": settings.rag_rewrite_provider,
        "rag_hyde_provider": settings.rag_hyde_provider,
        "rag_rerank_provider": settings.rag_rerank_provider,
        "rag_generation_provider": settings.rag_generation_provider,
        "rag_trace_provider": settings.rag_trace_provider,
        "rag_security_provider": settings.rag_security_provider,
        "rag_state_provider": settings.rag_state_provider,
    }
    settings.rag_chat_rate_limit = 2
    settings.rag_metadata_provider = "heuristic"
    settings.rag_embedding_provider = "deterministic"
    settings.rag_vector_store_provider = "memory"
    settings.rag_object_store_provider = "local"
    settings.rag_rewrite_provider = "heuristic"
    settings.rag_hyde_provider = "heuristic"
    settings.rag_rerank_provider = "lexical"
    settings.rag_generation_provider = "extractive"
    settings.rag_trace_provider = "memory"
    settings.rag_security_provider = "memory"
    settings.rag_state_provider = "memory"
    get_container.cache_clear()
    container = get_container()
    source = tmp_path / "guide.md"
    source.write_text("# MQTT\n\n默认端口是1883。", encoding="utf-8")

    with TestClient(app) as client:
        import asyncio

        bootstrap = client.post(
            "/api/v1/security/bootstrap",
            headers={"x-bootstrap-token": settings.security_bootstrap_token},
            json={
                "username": "rate-test-user",
                "password": "StrongPassword123!",
                "tenant_name": "Rate Tenant",
                "tenant_slug": "rate-tenant",
            },
        )
        assert bootstrap.status_code == 201, bootstrap.text
        headers = {"authorization": f"Bearer {bootstrap.json()['access_token']}"}
        tenant_id = bootstrap.json()["tenant_id"]
        asyncio.run(container.ingestion.ingest_path(source, force=True, tenant_id=tenant_id))
        first = client.post("/api/v1/chat", json={"query": "MQTT端口？"}, headers=headers)
        second = client.post("/api/v1/chat", json={"query": "MQTT端口？"}, headers=headers)
        third = client.post("/api/v1/chat", json={"query": "MQTT端口？"}, headers=headers)
        assert first.status_code == second.status_code == 200
        assert first.headers["x-ratelimit-limit"] == "2"
        assert third.status_code == 429
        assert "retry-after" in third.headers

        session_id = first.json()["session_id"]
        history = client.get(f"/api/v1/chat/sessions/{session_id}", headers=headers)
        assert history.status_code == 200
        assert len(history.json()["history"]) == 2
        cleared = client.delete(f"/api/v1/chat/sessions/{session_id}", headers=headers)
        assert cleared.status_code == 204
        assert (
            client.get(f"/api/v1/chat/sessions/{session_id}", headers=headers).json()["history"]
            == []
        )

    settings.rag_chat_rate_limit = original_limit
    for name, value in original_providers.items():
        setattr(settings, name, value)
    get_container.cache_clear()
