from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import asdict, dataclass
from pathlib import Path

from app.core.container import get_container


@dataclass(slots=True)
class EvaluationSummary:
    total: int
    recall_at_1: float
    recall_at_5: float
    recall_at_10: float
    recall_at_20: float
    mrr: float


async def evaluate(dataset_path: Path) -> EvaluationSummary:
    cases = json.loads(dataset_path.read_text(encoding="utf-8"))
    retriever = get_container().rag.retriever
    hits = {1: 0, 5: 0, 10: 0, 20: 0}
    reciprocal_rank = 0.0
    original_final_top_k = retriever.final_top_k
    retriever.final_top_k = 20
    try:
        for case in cases:
            results = await retriever.retrieve(case["question"])
            expected = case["expected_document"]
            rank = next(
                (
                    index + 1
                    for index, item in enumerate(results)
                    if item.filename == expected or item.document_id == expected
                ),
                None,
            )
            if rank:
                reciprocal_rank += 1.0 / rank
                for k in hits:
                    hits[k] += int(rank <= k)
    finally:
        retriever.final_top_k = original_final_top_k
    total = len(cases)
    return EvaluationSummary(
        total,
        *(hits[k] / total if total else 0.0 for k in (1, 5, 10, 20)),
        reciprocal_rank / total if total else 0.0,
    )


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("dataset", type=Path)
    args = parser.parse_args()
    print(json.dumps(asdict(await evaluate(args.dataset)), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
