from __future__ import annotations

import argparse
import asyncio

from pymilvus import MilvusClient
from rag_core.infrastructure import MilvusVectorStore

OUTPUT_FIELDS = [
    "chunk_id",
    "document_id",
    "tenant_id",
    "filename",
    "chunk_index",
    "content",
    "embedding_text",
    "metadata_json",
    "embedding",
]


async def migrate(
    source_uri: str,
    target_uri: str,
    source_collection: str,
    target_collection: str,
    batch_size: int,
) -> int:
    if source_uri == target_uri and source_collection == target_collection:
        raise ValueError("source and target collections must be different")

    source_client = MilvusClient(uri=source_uri)
    target_client = MilvusClient(uri=target_uri)
    if not source_client.has_collection(source_collection):
        raise ValueError(f"source collection does not exist: {source_collection}")

    description = source_client.describe_collection(source_collection)
    source_fields = {field["name"] for field in description["fields"]}
    missing = set(OUTPUT_FIELDS) - source_fields
    if missing:
        raise ValueError(f"source collection is missing fields: {sorted(missing)}")

    vector_field = next(
        field for field in description["fields"] if field["name"] == "embedding"
    )
    embedding_dimension = int(vector_field["params"]["dim"])
    target = MilvusVectorStore(target_uri, target_collection)
    await target.ensure_schema(embedding_dimension)
    target_count = target_client.query(
        target_collection, filter="id >= 0", output_fields=["count(*)"]
    )
    if target_count and int(target_count[0].get("count(*)", 0)) > 0:
        raise ValueError(
            f"target collection is not empty: {target_collection}; use a fresh collection"
        )

    iterator = source_client.query_iterator(
        collection_name=source_collection,
        batch_size=batch_size,
        filter="id >= 0",
        output_fields=OUTPUT_FIELDS,
    )
    migrated = 0
    try:
        while True:
            rows = iterator.next()
            if not rows:
                break
            payload = [
                {
                    "chunk_id": row["chunk_id"],
                    "document_id": row["document_id"],
                    "tenant_id": row.get("tenant_id", "default"),
                    "filename": row["filename"],
                    "chunk_index": row["chunk_index"],
                    "content": row["content"],
                    "embedding_text": row["embedding_text"],
                    "metadata_json": row.get("metadata_json", {}),
                    "embedding": row["embedding"],
                }
                for row in rows
            ]
            target_client.insert(target_collection, payload)
            migrated += len(payload)
            print(f"migrated={migrated}")
    finally:
        iterator.close()

    target_client.flush(target_collection)
    return migrated


async def main() -> None:
    parser = argparse.ArgumentParser(
        description="Copy a dense-only Milvus collection into a Dense+BM25 collection"
    )
    parser.add_argument("--uri", dest="target_uri", default="http://localhost:19530")
    parser.add_argument("--source-uri", default=None)
    parser.add_argument("--source", required=True)
    parser.add_argument("--target", required=True)
    parser.add_argument("--batch-size", type=int, default=500)
    args = parser.parse_args()
    migrated = await migrate(
        args.source_uri or args.target_uri,
        args.target_uri,
        args.source,
        args.target,
        args.batch_size,
    )
    print(f"completed: {migrated} chunks copied to {args.target}")


if __name__ == "__main__":
    asyncio.run(main())
