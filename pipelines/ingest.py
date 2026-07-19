from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from app.core.container import get_container


async def main() -> None:
    parser = argparse.ArgumentParser(description="Clean, enrich, chunk, embed and ingest documents")
    parser.add_argument("path", type=Path)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--tenant-slug", default="default")
    args = parser.parse_args()
    container = get_container()
    tenant = await container.security.repository.get_tenant_by_slug(args.tenant_slug)
    if tenant is None:
        raise ValueError(f"Unknown tenant slug: {args.tenant_slug}")
    service = container.ingestion
    if args.path.is_dir():
        results = await service.ingest_directory(
            args.path, force=args.force, tenant_id=tenant.tenant_id
        )
    else:
        results = [
            await service.ingest_path(
                args.path, force=args.force, tenant_id=tenant.tenant_id
            )
        ]
    for result in results:
        print(f"{result.filename}: chunks={result.chunk_count}, skipped={result.skipped}")


if __name__ == "__main__":
    asyncio.run(main())
