from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)

    app_name: str = "Enterprise RAG"
    app_env: str = "development"
    app_debug: bool = True
    log_level: str = "INFO"
    rag_use_mocks: bool = True
    rag_embedding_model: str = "Qwen3-Embedding-8B"
    rag_embedding_dimension: int = 1024
    rag_generation_model: str = "Qwen2.5-72B"
    rag_rewrite_model: str = "Qwen2.5-7B-Instruct"
    rag_rerank_model: str = "bge-reranker-v2-m3"
    rag_short_document_limit: int = 6000
    rag_chunk_size: int = 6000
    rag_chunk_overlap: int = 500
    rag_vector_top_k: int = 20
    rag_final_top_k: int = 5
    rag_hyde_enabled: bool = True
    rag_hyde_model: str = "Qwen2.5-7B-Instruct"
    rag_session_ttl_seconds: int = 86400
    rag_chat_rate_limit: int = 30
    rag_upload_rate_limit: int = 10
    rag_rate_window_seconds: int = 60
    rag_hnsw_m: int = 16
    rag_hnsw_ef_construction: int = 256
    rag_hnsw_ef_search: int = 64
    model_gateway_base_url: str = "http://localhost:9000/v1"
    model_gateway_api_key: str = "change-me"
    rerank_endpoint: str = "http://localhost:9010/rerank"
    milvus_uri: str = "http://localhost:19530"
    milvus_collection: str = "enterprise_knowledge"
    postgres_dsn: str = "postgresql+asyncpg://rag:rag@localhost:5432/rag"
    redis_url: str = "redis://localhost:6379/0"
    minio_endpoint: str = "localhost:9001"
    minio_access_key: str = "minioadmin"
    minio_secret_key: str = "minioadmin"
    minio_bucket: str = "rag-assets"
    minio_secure: bool = False
    data_raw_dir: Path = Path("data/raw")
    data_processed_dir: Path = Path("data/processed")
    data_asset_dir: Path = Path("data/assets")
    data_checkpoint_file: Path = Path("data/checkpoints/ingestion.json")
    data_reports_dir: Path = Path("data/reports")
    request_timeout_seconds: float = Field(default=60.0, gt=0)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
