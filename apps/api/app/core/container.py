from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from rag_core.cleaning import DualFormatExporter, RegexDocumentCleaner, default_parser_registry
from rag_core.config import get_settings
from rag_core.distributed import InMemoryLockManager, InMemoryRateLimiter, InMemorySessionStore
from rag_core.enrichment import HeuristicMetadataEnricher, OpenAICompatibleMetadataEnricher
from rag_core.generation import ExtractiveAnswerGenerator, OpenAICompatibleAnswerGenerator
from rag_core.governance import DataGovernanceService
from rag_core.infrastructure import (
    HttpReranker,
    InMemoryCache,
    InMemorySecurityRepository,
    InMemoryTraceRepository,
    InMemoryVectorStore,
    LocalObjectStore,
    MilvusVectorStore,
    MinioObjectStore,
    PostgresSecurityRepository,
    PostgresTraceRepository,
    RedisCache,
    RedisStateBackend,
)
from rag_core.ingestion import (
    DeterministicHashEmbedder,
    OpenAICompatibleEmbedder,
    RecursiveDocumentChunker,
)
from rag_core.retrieval import (
    HeuristicHydeGenerator,
    HeuristicQueryRewriter,
    LexicalReranker,
    OpenAICompatibleHydeGenerator,
    OpenAICompatibleQueryRewriter,
)
from rag_core.security import JwtCodec
from rag_core.security_service import SecurityService
from rag_core.services import IngestionService, RagService


@dataclass(slots=True)
class Container:
    ingestion: IngestionService
    rag: RagService
    vector_store: object
    object_store: object
    traces: object
    sessions: object
    locks: object
    rate_limiter: object
    governance: DataGovernanceService
    security: SecurityService
    redis_backend: object | None = None


@lru_cache(maxsize=1)
def get_container() -> Container:
    settings = get_settings()
    parser_registry = default_parser_registry(settings.data_asset_dir / "extracted")
    cleaner = RegexDocumentCleaner()
    exporter = DualFormatExporter()
    chunker = RecursiveDocumentChunker(
        settings.rag_short_document_limit,
        settings.rag_chunk_size,
        settings.rag_chunk_overlap,
    )

    metadata_provider = _provider(
        settings.rag_metadata_provider, settings.rag_use_mocks, "heuristic", "openai"
    )
    embedding_provider = _provider(
        settings.rag_embedding_provider, settings.rag_use_mocks, "deterministic", "openai"
    )
    vector_store_provider = _provider(
        settings.rag_vector_store_provider, settings.rag_use_mocks, "memory", "milvus"
    )
    object_store_provider = _provider(
        settings.rag_object_store_provider, settings.rag_use_mocks, "local", "minio"
    )
    rewrite_provider = _provider(
        settings.rag_rewrite_provider, settings.rag_use_mocks, "heuristic", "openai"
    )
    hyde_provider = _provider(
        settings.rag_hyde_provider, settings.rag_use_mocks, "heuristic", "openai"
    )
    rerank_provider = _provider(
        settings.rag_rerank_provider, settings.rag_use_mocks, "lexical", "http"
    )
    generation_provider = _provider(
        settings.rag_generation_provider, settings.rag_use_mocks, "extractive", "openai"
    )

    trace_provider = _provider(
        settings.rag_trace_provider, settings.rag_use_mocks, "memory", "postgres"
    )
    security_provider = _provider(
        settings.rag_security_provider, settings.rag_use_mocks, "memory", "postgres"
    )
    state_provider = _provider(
        settings.rag_state_provider, settings.rag_use_mocks, "memory", "redis"
    )

    if metadata_provider == "heuristic":
        enricher = HeuristicMetadataEnricher()
    else:
        enricher = OpenAICompatibleMetadataEnricher(
            settings.model_gateway_base_url,
            settings.model_gateway_api_key,
            settings.rag_generation_model,
            settings.request_timeout_seconds,
        )

    if embedding_provider == "deterministic":
        embedder = DeterministicHashEmbedder(settings.rag_embedding_dimension)
    else:
        embedder = OpenAICompatibleEmbedder(
            settings.model_gateway_base_url,
            settings.model_gateway_api_key,
            settings.rag_embedding_model,
            settings.rag_embedding_dimension,
            settings.request_timeout_seconds,
        )

    if vector_store_provider == "memory":
        vector_store = InMemoryVectorStore()
    else:
        vector_store = MilvusVectorStore(
            settings.milvus_uri,
            settings.milvus_collection,
            settings.rag_hnsw_m,
            settings.rag_hnsw_ef_construction,
            settings.rag_hnsw_ef_search,
        )

    if object_store_provider == "local":
        object_store = LocalObjectStore(
            settings.data_asset_dir / "public",
            signing_secret=settings.security_asset_signing_secret,
        )
    else:
        object_store = MinioObjectStore(
            settings.minio_endpoint,
            settings.minio_access_key,
            settings.minio_secret_key,
            settings.minio_bucket,
            settings.minio_secure,
            signing_secret=settings.security_asset_signing_secret,
        )

    if rewrite_provider == "heuristic":
        rewriter = HeuristicQueryRewriter()
    else:
        rewriter = OpenAICompatibleQueryRewriter(
            settings.model_gateway_base_url,
            settings.model_gateway_api_key,
            settings.rag_rewrite_model,
        )

    if hyde_provider == "heuristic":
        hyde_generator = HeuristicHydeGenerator()
    else:
        hyde_generator = OpenAICompatibleHydeGenerator(
            settings.model_gateway_base_url,
            settings.model_gateway_api_key,
            settings.rag_hyde_model,
        )

    if rerank_provider == "lexical":
        reranker = LexicalReranker()
    else:
        reranker = HttpReranker(
            settings.rerank_endpoint,
            settings.rag_rerank_model,
            settings.rerank_api_key,
        )

    if generation_provider == "extractive":
        generator = ExtractiveAnswerGenerator()
    else:
        generator = OpenAICompatibleAnswerGenerator(
            settings.model_gateway_base_url,
            settings.model_gateway_api_key,
            settings.rag_generation_model,
            120.0,
        )

    redis_backend = None
    if state_provider == "memory":
        cache = InMemoryCache()
        sessions = InMemorySessionStore()
        locks = InMemoryLockManager()
        rate_limiter = InMemoryRateLimiter()
    else:
        redis_backend = RedisStateBackend(settings.redis_url)
        cache = RedisCache(client=redis_backend.client)
        sessions = redis_backend.sessions
        locks = redis_backend.locks
        rate_limiter = redis_backend.rate_limiter

    traces = (
        PostgresTraceRepository(settings.postgres_dsn)
        if trace_provider == "postgres"
        else InMemoryTraceRepository()
    )
    security_repository = (
        PostgresSecurityRepository(settings.postgres_dsn)
        if security_provider == "postgres"
        else InMemorySecurityRepository()
    )

    security = SecurityService(
        security_repository,
        JwtCodec(
            settings.security_jwt_secret,
            settings.security_jwt_issuer,
            settings.security_jwt_audience,
            settings.security_access_token_ttl_seconds,
        ),
    )
    governance = DataGovernanceService(parser_registry, cleaner, settings.data_reports_dir)
    ingestion = IngestionService(
        parser_registry,
        cleaner,
        exporter,
        enricher,
        chunker,
        embedder,
        vector_store,
        object_store,
        settings.data_processed_dir,
        settings.data_checkpoint_file,
        locks,
    )
    rag = RagService(
        rewriter,
        hyde_generator,
        embedder,
        vector_store,
        reranker,
        generator,
        traces,
        cache,
        sessions,
        vector_top_k=settings.rag_vector_top_k,
        rerank_candidate_count=settings.rag_rerank_candidate_count,
        final_top_k=settings.rag_final_top_k,
        session_ttl_seconds=settings.rag_session_ttl_seconds,
        hyde_enabled=settings.rag_hyde_enabled,
    )
    return Container(
        ingestion=ingestion,
        rag=rag,
        vector_store=vector_store,
        object_store=object_store,
        traces=traces,
        sessions=sessions,
        locks=locks,
        rate_limiter=rate_limiter,
        governance=governance,
        security=security,
        redis_backend=redis_backend,
    )


def _provider(value: str, use_mocks: bool, mock_default: str, production_default: str) -> str:
    if value != "auto":
        return value
    return mock_default if use_mocks else production_default
