from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Sequence

from rag_core.contracts import Embedder, Reranker, VectorStore
from rag_core.models import RetrievalResult


class ParentDocumentRetriever:
    def __init__(
        self,
        embedder: Embedder,
        vector_store: VectorStore,
        reranker: Reranker,
        vector_top_k: int = 20,
        rerank_candidate_count: int = 20,
        final_top_k: int = 5,
        lexical_top_k: int = 20,
        hybrid_enabled: bool = True,
        rrf_k: int = 60,
    ) -> None:
        self.embedder = embedder
        self.vector_store = vector_store
        self.reranker = reranker
        self.vector_top_k = vector_top_k
        self.rerank_candidate_count = rerank_candidate_count
        self.final_top_k = final_top_k
        self.lexical_top_k = lexical_top_k
        self.hybrid_enabled = hybrid_enabled
        self.rrf_k = rrf_k

    async def retrieve(
        self,
        query: str,
        query_variants: Sequence[str] = (),
        tenant_id: str = "default",
        lexical_variants: Sequence[str] | None = None,
    ) -> list[RetrievalResult]:
        search_texts = _unique_non_empty([query, *query_variants])
        embeddings = await self.embedder.embed(search_texts)
        fused_scores: dict[str, float] = defaultdict(float)
        best_vector_scores: dict[str, float] = {}
        best_lexical_scores: dict[str, float] = {}
        matched_routes: dict[str, set[str]] = defaultdict(set)

        for route_index, (_search_text, embedding) in enumerate(
            zip(search_texts, embeddings, strict=True)
        ):
            hits = await self.vector_store.search(embedding, self.vector_top_k, tenant_id)
            route_name = "query" if route_index == 0 else f"variant_{route_index}"
            for rank, hit in enumerate(hits, start=1):
                document_id = hit.chunk.document_id
                fused_scores[document_id] += 1.0 / (self.rrf_k + rank)
                best_vector_scores[document_id] = max(
                    best_vector_scores.get(document_id, -1.0),
                    hit.score,
                )
                matched_routes[document_id].add(route_name)

        lexical_texts = _unique_non_empty(
            [query, *(lexical_variants if lexical_variants is not None else query_variants)]
        )
        if self.hybrid_enabled:
            for route_index, search_text in enumerate(lexical_texts):
                hits = await self.vector_store.lexical_search(
                    search_text, self.lexical_top_k, tenant_id
                )
                route_name = "bm25_query" if route_index == 0 else f"bm25_variant_{route_index}"
                for rank, hit in enumerate(hits, start=1):
                    document_id = hit.chunk.document_id
                    fused_scores[document_id] += 1.0 / (self.rrf_k + rank)
                    best_lexical_scores[document_id] = max(
                        best_lexical_scores.get(document_id, 0.0),
                        hit.score,
                    )
                    matched_routes[document_id].add(route_name)

        document_ids = sorted(fused_scores, key=fused_scores.get, reverse=True)
        chunks = await self.vector_store.get_document_chunks(document_ids, tenant_id)
        grouped = defaultdict(list)
        for chunk in chunks:
            grouped[chunk.document_id].append(chunk)

        max_fused = max(fused_scores.values(), default=1.0)
        candidates = []
        for document_id in document_ids:
            document_chunks = sorted(
                grouped[document_id],
                key=lambda item: item.chunk_index,
            )
            if not document_chunks:
                continue
            normalized_rrf = fused_scores[document_id] / max_fused
            vector_score = best_vector_scores.get(document_id, 0.0)
            combined_score = vector_score * 0.7 + normalized_rrf * 0.3
            metadata = dict(document_chunks[0].metadata)
            metadata.update(
                {
                    "rrf_score": fused_scores[document_id],
                    "vector_score": vector_score,
                    "bm25_score": best_lexical_scores.get(document_id, 0.0),
                    "matched_routes": sorted(matched_routes[document_id]),
                    "search_variants": search_texts,
                    "lexical_variants": lexical_texts if self.hybrid_enabled else [],
                }
            )
            candidates.append(
                RetrievalResult(
                    document_id=document_id,
                    filename=document_chunks[0].filename,
                    content="\n\n".join(chunk.content for chunk in document_chunks),
                    score=combined_score,
                    chunks=document_chunks,
                    metadata=metadata,
                )
            )

        candidates.sort(key=lambda item: item.score, reverse=True)
        reranked = await self.reranker.rerank(query, candidates[: self.rerank_candidate_count])
        return reranked[: self.final_top_k]


class LexicalReranker:
    async def rerank(
        self,
        query: str,
        candidates: Sequence[RetrievalResult],
    ) -> list[RetrievalResult]:
        query_terms = set(_terms(query))
        reranked: list[RetrievalResult] = []
        for candidate in candidates:
            document_terms = set(_terms(candidate.content + " " + candidate.filename))
            lexical = len(query_terms & document_terms) / max(len(query_terms), 1)
            candidate.score = candidate.score * 0.65 + lexical * 0.35
            reranked.append(candidate)
        return sorted(reranked, key=lambda item: item.score, reverse=True)


def _unique_non_empty(values: Sequence[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = value.strip()
        if normalized and normalized not in seen:
            seen.add(normalized)
            result.append(normalized)
    return result


def _terms(text: str) -> list[str]:
    words = re.findall(r"[A-Za-z0-9_.+-]+|[\u4e00-\u9fff]{2,6}", text.lower())
    chinese = re.findall(r"[\u4e00-\u9fff]", text)
    bigrams = ["".join(chinese[index : index + 2]) for index in range(max(len(chinese) - 1, 0))]
    return words + bigrams
