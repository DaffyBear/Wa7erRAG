from prometheus_client import Counter, Histogram

REQUEST_COUNT = Counter("rag_api_requests_total", "RAG API requests", ["operation", "status"])
STAGE_LATENCY = Histogram("rag_stage_latency_seconds", "RAG stage latency", ["stage"])
INGESTED_DOCUMENTS = Counter("rag_ingested_documents_total", "Ingested documents", ["status"])
FEEDBACK_COUNT = Counter("rag_feedback_total", "User feedback", ["value"])
