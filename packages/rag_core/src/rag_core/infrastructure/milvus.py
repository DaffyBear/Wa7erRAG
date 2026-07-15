from __future__ import annotations

import asyncio
from collections.abc import Sequence
from typing import Any

from rag_core.models import DocumentChunk, VectorHit


class MilvusVectorStore:
    def __init__(
        self,
        uri: str,
        collection_name: str,
        hnsw_m: int = 16,
        ef_construction: int = 256,
        ef_search: int = 64,
        consistency_level: str = "Strong",
    ) -> None:
        from pymilvus import MilvusClient

        self.client = MilvusClient(uri=uri)
        self.collection_name = collection_name
        self.hnsw_m = hnsw_m
        self.ef_construction = ef_construction
        self.ef_search = ef_search
        self.consistency_level = consistency_level
        self.dimension: int | None = None

    async def ensure_schema(self, embedding_dimension: int) -> None:
        await asyncio.to_thread(self._ensure_schema, embedding_dimension)

    def _ensure_schema(self, embedding_dimension: int) -> None:
        from pymilvus import DataType, MilvusClient

        if self.client.has_collection(self.collection_name):
            description = self.client.describe_collection(self.collection_name)
            field_names = {field["name"] for field in description["fields"]}
            required_fields = {"embedding", "tenant_id", "document_id", "chunk_id"}
            missing_fields = required_fields - field_names
            if missing_fields:
                raise ValueError(
                    f"Milvus collection is missing required fields: {sorted(missing_fields)}; "
                    "rebuild the collection explicitly"
                )
            vector_field = next(
                field for field in description["fields"] if field["name"] == "embedding"
            )
            existing_dimension = int(vector_field["params"]["dim"])
            if existing_dimension != embedding_dimension:
                raise ValueError(
                    "Milvus collection dimension is "
                    f"{existing_dimension}, expected {embedding_dimension}; "
                    "rebuild the collection explicitly"
                )
            self.dimension = existing_dimension
            self.client.load_collection(self.collection_name)
            return
        schema = MilvusClient.create_schema(auto_id=True, enable_dynamic_field=False)
        schema.add_field("id", DataType.INT64, is_primary=True, auto_id=True)
        schema.add_field("chunk_id", DataType.VARCHAR, max_length=64)
        schema.add_field("document_id", DataType.VARCHAR, max_length=64)
        schema.add_field("tenant_id", DataType.VARCHAR, max_length=64)
        schema.add_field("filename", DataType.VARCHAR, max_length=512)
        schema.add_field("chunk_index", DataType.INT64)
        schema.add_field("content", DataType.VARCHAR, max_length=65535)
        schema.add_field("embedding_text", DataType.VARCHAR, max_length=65535)
        schema.add_field("metadata_json", DataType.JSON)
        schema.add_field("embedding", DataType.FLOAT_VECTOR, dim=embedding_dimension)
        index_params = self.client.prepare_index_params()
        index_params.add_index(
            field_name="embedding",
            index_type="HNSW",
            metric_type="COSINE",
            params={"M": self.hnsw_m, "efConstruction": self.ef_construction},
        )
        index_params.add_index(field_name="document_id", index_type="INVERTED")
        index_params.add_index(field_name="tenant_id", index_type="INVERTED")
        index_params.add_index(field_name="filename", index_type="INVERTED")
        self.client.create_collection(
            self.collection_name, schema=schema, index_params=index_params
        )
        self.client.load_collection(self.collection_name)
        self.dimension = embedding_dimension

    async def upsert(
        self, chunks: Sequence[DocumentChunk], embeddings: Sequence[Sequence[float]]
    ) -> None:
        if len(chunks) != len(embeddings):
            raise ValueError("chunks and embeddings must have identical lengths")
        rows = [
            {
                "chunk_id": chunk.chunk_id,
                "document_id": chunk.document_id,
                "tenant_id": str(chunk.metadata.get("tenant_id", "default")),
                "filename": chunk.filename,
                "chunk_index": chunk.chunk_index,
                "content": chunk.content,
                "embedding_text": chunk.embedding_text,
                "metadata_json": chunk.metadata,
                "embedding": list(embedding),
            }
            for chunk, embedding in zip(chunks, embeddings, strict=True)
        ]
        await asyncio.to_thread(self.client.insert, self.collection_name, rows)

    async def delete_document(self, document_id: str, tenant_id: str = "default") -> None:
        escaped = document_id.replace('"', '\\"')
        await asyncio.to_thread(
            self.client.delete,
            self.collection_name,
            filter=f'document_id == "{escaped}" and tenant_id == "{tenant_id}"',
        )

    async def search(
        self, embedding: Sequence[float], limit: int, tenant_id: str = "default"
    ) -> list[VectorHit]:
        result = await asyncio.to_thread(
            self.client.search,
            self.collection_name,
            data=[list(embedding)],
            anns_field="embedding",
            filter=f'tenant_id == "{tenant_id}"',
            limit=limit,
            search_params={"metric_type": "COSINE", "params": {"ef": self.ef_search}},
            consistency_level=self.consistency_level,
            output_fields=[
                "chunk_id",
                "document_id",
                "filename",
                "chunk_index",
                "content",
                "embedding_text",
                "metadata_json",
            ],
        )
        return [
            VectorHit(_row_to_chunk(item["entity"]), float(item["distance"])) for item in result[0]
        ]

    async def get_document_chunks(
        self, document_ids: Sequence[str], tenant_id: str = "default"
    ) -> list[DocumentChunk]:
        if not document_ids:
            return []
        quoted = ", ".join(f'"{item.replace(chr(34), chr(92) + chr(34))}"' for item in document_ids)
        rows = await asyncio.to_thread(
            self.client.query,
            self.collection_name,
            filter=f'document_id in [{quoted}] and tenant_id == "{tenant_id}"',
            output_fields=[
                "chunk_id",
                "document_id",
                "filename",
                "chunk_index",
                "content",
                "embedding_text",
                "metadata_json",
            ],
            limit=16384,
            consistency_level=self.consistency_level,
        )
        return sorted(
            (_row_to_chunk(row) for row in rows),
            key=lambda chunk: (chunk.document_id, chunk.chunk_index),
        )

    async def count(self, tenant_id: str = "default") -> int:
        rows = await asyncio.to_thread(
            self.client.query,
            self.collection_name,
            filter=f'id >= 0 and tenant_id == "{tenant_id}"',
            output_fields=["count(*)"],
            consistency_level=self.consistency_level,
        )
        return int(rows[0].get("count(*)", 0)) if rows else 0


def _row_to_chunk(row: dict[str, Any]) -> DocumentChunk:
    return DocumentChunk(
        chunk_id=row["chunk_id"],
        document_id=row["document_id"],
        filename=row["filename"],
        chunk_index=int(row["chunk_index"]),
        content=row["content"],
        embedding_text=row["embedding_text"],
        metadata=row.get("metadata_json") or {},
    )
