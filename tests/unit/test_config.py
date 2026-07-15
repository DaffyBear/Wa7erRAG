from rag_core.config import Settings


def test_production_defaults_match_documented_architecture() -> None:
    settings = Settings(_env_file=None)

    assert settings.rag_embedding_dimension == 1024
    assert settings.rag_chunk_size == 6000
    assert settings.rag_chunk_overlap == 500
    assert settings.rag_vector_top_k == 20
    assert settings.rag_hnsw_m == 16
    assert settings.rag_hnsw_ef_construction == 256
