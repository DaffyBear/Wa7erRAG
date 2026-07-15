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
    redis_backend = None

    if settings.rag_use_mocks:
        enricher = HeuristicMetadataEnricher()
        embedder = DeterministicHashEmbedder(settings.rag_embedding_dimension)
        vector_store = InMemoryVectorStore()
        object_store = LocalObjectStore(
            settings.data_asset_dir / "public",
            signing_secret=settings.security_asset_signing_secret,
        )
        rewriter = HeuristicQueryRewriter()
        hyde_generator = HeuristicHydeGenerator()
        reranker = LexicalReranker()
        generator = ExtractiveAnswerGenerator()
        traces = InMemoryTraceRepository()
        cache = InMemoryCache()
        sessions = InMemorySessionStore()
        locks = InMemoryLockManager()
        rate_limiter = InMemoryRateLimiter()
        security_repository = InMemorySecurityRepository()
    else:
        redis_backend = RedisStateBackend(settings.redis_url)
        enricher = OpenAICompatibleMetadataEnricher(
            settings.model_gateway_base_url,
            settings.model_gateway_api_key,
            settings.rag_generation_model,
            settings.request_timeout_seconds,
        )
        embedder = OpenAICompatibleEmbedder(
            settings.model_gateway_base_url,
            settings.model_gateway_api_key,
            settings.rag_embedding_model,
            settings.rag_embedding_dimension,
            settings.request_timeout_seconds,
        )
        vector_store = MilvusVectorStore(
            settings.milvus_uri,
            settings.milvus_collection,
            settings.rag_hnsw_m,
            settings.rag_hnsw_ef_construction,
            settings.rag_hnsw_ef_search,
        )
        object_store = MinioObjectStore(
            settings.minio_endpoint,
            settings.minio_access_key,
            settings.minio_secret_key,
            settings.minio_bucket,
            settings.minio_secure,
            signing_secret=settings.security_asset_signing_secret,
        )
        rewriter = OpenAICompatibleQueryRewriter(
            settings.model_gateway_base_url,
            settings.model_gateway_api_key,
            settings.rag_rewrite_model,
        )
        hyde_generator = OpenAICompatibleHydeGenerator(
            settings.model_gateway_base_url,
            settings.model_gateway_api_key,
            settings.rag_hyde_model,
        )
        reranker = HttpReranker(settings.rerank_endpoint, settings.rag_rerank_model)
        generator = OpenAICompatibleAnswerGenerator(
            settings.model_gateway_base_url,
            settings.model_gateway_api_key,
            settings.rag_generation_model,
            120.0,
        )
        traces = PostgresTraceRepository(settings.postgres_dsn)
        cache = RedisCache(settings.redis_url)
        sessions = redis_backend.sessions
        locks = redis_backend.locks
        rate_limiter = redis_backend.rate_limiter
        security_repository = PostgresSecurityRepository(settings.postgres_dsn)

    security = SecurityService(
        security_repository,
        JwtCodec(
            settings.security_jwt_secret,
            settings.security_jwt_issuer,
            settings.security_jwt_audience,
            settings.security_access_token_ttl_seconds,
        ),
    )
    governance = DataGovernanceService(
        parser_registry,
        cleaner,
        settings.data_reports_dir,
    )
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
        settings.rag_vector_top_k,
        settings.rag_final_top_k,
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
