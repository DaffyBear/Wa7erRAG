from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[4]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        extra="ignore",
        case_sensitive=False,
    )

    app_name: str = "Enterprise RAG"
    app_env: str = "development"
    app_debug: bool = True
    log_level: str = "INFO"
    security_enabled: bool = True
    security_jwt_secret: str = "development-only-change-this-secret-32chars"
    security_jwt_issuer: str = "wa7errag"
    security_jwt_audience: str = "wa7errag-api"
    security_access_token_ttl_seconds: int = 3600
    security_login_rate_limit: int = 10
    security_login_rate_window_seconds: int = 300
    security_bootstrap_token: str = "change-me-bootstrap-token"
    security_asset_signing_secret: str = "development-only-asset-signing-secret"
    rag_use_mocks: bool = True
    rag_metadata_provider: Literal["auto", "heuristic", "openai"] = "auto"
    rag_embedding_provider: Literal["auto", "deterministic", "openai"] = "auto"
    rag_vector_store_provider: Literal["auto", "memory", "milvus"] = "auto"
    rag_object_store_provider: Literal["auto", "local", "minio"] = "auto"
    rag_rewrite_provider: Literal["auto", "heuristic", "openai"] = "auto"
    rag_hyde_provider: Literal["auto", "heuristic", "openai"] = "auto"
    rag_rerank_provider: Literal["auto", "lexical", "http"] = "auto"
    rag_generation_provider: Literal["auto", "extractive", "openai"] = "auto"
    rag_trace_provider: Literal["auto", "memory", "postgres"] = "auto"
    rag_security_provider: Literal["auto", "memory", "postgres"] = "auto"
    rag_state_provider: Literal["auto", "memory", "redis"] = "auto"
    rag_embedding_model: str = "Qwen3-Embedding-8B"
    rag_embedding_dimension: int = 1024
    rag_generation_model: str = "Qwen2.5-72B"
    rag_rewrite_model: str = "Qwen2.5-7B-Instruct"
    rag_rerank_model: str = "bge-reranker-v2-m3"
    rag_short_document_limit: int = 6000
    rag_chunk_size: int = 6000
    rag_chunk_overlap: int = 500
    rag_vector_top_k: int = 20
    rag_rerank_candidate_count: int = 20
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
    rerank_api_key: str = ""
    milvus_uri: str = "http://localhost:19530"
    milvus_collection: str = "enterprise_knowledge_tenant_v1"
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
