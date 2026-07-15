from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from app.core.container import get_container


async def main() -> None:
    parser = argparse.ArgumentParser(description="Clean, enrich, chunk, embed and ingest documents")
    parser.add_argument("path", type=Path)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    service = get_container().ingestion
    if args.path.is_dir():
        results = await service.ingest_directory(args.path, force=args.force)
    else:
        results = [await service.ingest_path(args.path, force=args.force)]
    for result in results:
        print(f"{result.filename}: chunks={result.chunk_count}, skipped={result.skipped}")


if __name__ == "__main__":
    asyncio.run(main())
