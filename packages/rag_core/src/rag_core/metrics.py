from prometheus_client import Counter, Gauge, Histogram

REQUEST_COUNT = Counter("rag_api_requests_total", "RAG API requests", ["operation", "status"])
STAGE_LATENCY = Histogram("rag_stage_latency_seconds", "RAG stage latency", ["stage"])
INGESTED_DOCUMENTS = Counter("rag_ingested_documents_total", "Ingested documents", ["status"])
FEEDBACK_COUNT = Counter("rag_feedback_total", "User feedback", ["value"])
RERANK_OPERATIONS = Counter(
    "rag_rerank_operations_total",
    "Rerank operation outcomes",
    ["outcome"],
)
RERANK_LATENCY = Histogram(
    "rag_rerank_latency_seconds",
    "Rerank latency by provider and outcome",
    ["provider", "outcome"],
)
RERANK_CANDIDATES = Histogram(
    "rag_rerank_candidates",
    "Number of candidates submitted for reranking",
    buckets=(1, 2, 5, 10, 20, 30, 50, 100),
)
RERANK_CIRCUIT_STATE = Gauge(
    "rag_rerank_circuit_state",
    "Rerank circuit state: 0 closed, 1 open, 2 half-open",
)
