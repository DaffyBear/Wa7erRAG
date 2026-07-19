from rag_core.config import Settings


def test_production_defaults_match_documented_architecture() -> None:
    settings = Settings(_env_file=None)

    assert settings.rag_embedding_dimension == 1024
    assert settings.rag_chunk_size == 6000
    assert settings.rag_chunk_overlap == 500
    assert settings.rag_vector_top_k == 20
    assert settings.rag_hnsw_m == 16
    assert settings.rag_hnsw_ef_construction == 256
    assert settings.rerank_timeout_seconds == 10.0
    assert settings.rerank_max_retries == 2
    assert settings.rerank_max_concurrency == 8
    assert settings.rerank_circuit_failure_threshold == 5
    assert settings.rerank_fallback_provider == "lexical"

def test_component_providers_can_override_mock_mode() -> None:
    settings = Settings(
        _env_file=None,
        rag_use_mocks=True,
        rag_embedding_provider="openai",
        rag_generation_provider="openai",
        rag_object_store_provider="local",
        rag_rerank_provider="lexical",
        rag_state_provider="redis",
    )

    assert settings.rag_embedding_provider == "openai"
    assert settings.rag_generation_provider == "openai"
    assert settings.rag_object_store_provider == "local"
    assert settings.rag_rerank_provider == "lexical"
    assert settings.rag_state_provider == "redis"


def test_embedding_gateway_can_be_configured_independently() -> None:
    settings = Settings(
        _env_file=None,
        model_gateway_base_url="https://chat.example/v1",
        model_gateway_api_key="chat-key",
        embedding_gateway_base_url="https://embedding.example/v1",
        embedding_gateway_api_key="embedding-key",
    )

    assert settings.embedding_gateway_base_url == "https://embedding.example/v1"
    assert settings.embedding_gateway_api_key == "embedding-key"
