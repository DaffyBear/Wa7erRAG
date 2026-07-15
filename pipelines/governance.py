from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from app.core.container import get_container


def main() -> None:
    parser = argparse.ArgumentParser(description="Data inventory, sampling and cleaning audit")
    subparsers = parser.add_subparsers(dest="command", required=True)

    audit = subparsers.add_parser("audit")
    audit.add_argument("data_root", type=Path)
    audit.add_argument("--sample-size", type=int, default=50)
    audit.add_argument("--seed", type=int, default=2026)
    audit.add_argument("--exclude-failures", action="store_true")

    review = subparsers.add_parser("import-review")
    review.add_argument("run_id")
    review.add_argument("review_csv", type=Path)

    compare = subparsers.add_parser("compare")
    compare.add_argument("baseline_run_id")
    compare.add_argument("current_run_id")

    subparsers.add_parser("list")
    args = parser.parse_args()
    service = get_container().governance
    if args.command == "audit":
        result = service.run_full_audit(
            args.data_root,
            sample_size=args.sample_size,
            seed=args.seed,
            include_failures=not args.exclude_failures,
        )
        print(json.dumps(asdict(result), ensure_ascii=False, indent=2))
    elif args.command == "import-review":
        result = service.import_review_results(args.run_id, args.review_csv)
        print(json.dumps(asdict(result), ensure_ascii=False, indent=2))
    elif args.command == "compare":
        print(service.compare_runs(args.baseline_run_id, args.current_run_id))
    else:
        print(
            json.dumps([asdict(item) for item in service.list_runs()], ensure_ascii=False, indent=2)
        )


if __name__ == "__main__":
    main()
