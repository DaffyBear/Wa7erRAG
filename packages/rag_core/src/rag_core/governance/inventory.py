from __future__ import annotations

import csv
import json
import math
from collections import Counter, defaultdict
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from rag_core.governance.models import InventoryRecord, InventorySummary
from rag_core.utils import sha256_file, stable_id

LENGTH_BUCKETS = (
    (500, "0000-0500"),
    (1000, "0501-1000"),
    (3000, "1001-3000"),
    (5000, "3001-5000"),
    (6000, "5001-6000"),
    (10000, "6001-10000"),
    (30000, "10001-30000"),
    (math.inf, "30001+"),
)


class InventoryScanner:
    def __init__(self, parser_registry: Any) -> None:
        self.parser_registry = parser_registry

    def scan(self, root: Path, run_id: str) -> tuple[InventorySummary, list[InventoryRecord]]:
        root = root.resolve()
        records: list[InventoryRecord] = []
        checksum_groups: dict[str, list[InventoryRecord]] = defaultdict(list)
        for path in sorted(item for item in root.rglob("*") if item.is_file()):
            record = self._scan_file(root, path)
            records.append(record)
            if record.checksum:
                checksum_groups[record.checksum].append(record)
        duplicate_files = 0
        for checksum, group in checksum_groups.items():
            if len(group) <= 1:
                continue
            duplicate_group = stable_id("duplicate", checksum)
            duplicate_files += len(group)
            for record in group:
                record.duplicate_group = duplicate_group
        summary = self._summary(run_id, root, records, duplicate_files)
        return summary, records

    def write_reports(
        self,
        output_dir: Path,
        summary: InventorySummary,
        records: list[InventoryRecord],
    ) -> dict[str, str]:
        output_dir.mkdir(parents=True, exist_ok=True)
        records_json = output_dir / "inventory_records.json"
        records_csv = output_dir / "inventory_records.csv"
        summary_json = output_dir / "inventory_summary.json"
        summary_md = output_dir / "inventory_summary.md"
        records_json.write_text(
            json.dumps([asdict(item) for item in records], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        with records_csv.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(
                handle, fieldnames=list(asdict(records[0]).keys()) if records else []
            )
            if records:
                writer.writeheader()
                writer.writerows(asdict(item) for item in records)
        summary.records_file = str(records_json)
        summary_json.write_text(
            json.dumps(asdict(summary), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        summary_md.write_text(self._markdown(summary), encoding="utf-8")
        return {
            "summary_json": str(summary_json),
            "summary_markdown": str(summary_md),
            "records_json": str(records_json),
            "records_csv": str(records_csv),
        }

    def _scan_file(self, root: Path, path: Path) -> InventoryRecord:
        relative = path.relative_to(root).as_posix()
        supported = self.parser_registry.supports(path)
        checksum = ""
        parse_status = "unsupported"
        parse_error = ""
        metrics = {
            "character_count": 0,
            "non_whitespace_count": 0,
            "line_count": 0,
            "paragraph_count": 0,
            "heading_count": 0,
            "table_row_count": 0,
            "image_count": 0,
        }
        try:
            checksum = sha256_file(path)
            if supported:
                document = self.parser_registry.parse(path)
                metrics = self._content_metrics(document.content, len(document.assets))
                parse_status = "parsed"
        except Exception as error:
            parse_status = "failed"
            parse_error = f"{type(error).__name__}: {error}"[:1000]
        stat = path.stat()
        return InventoryRecord(
            record_id=stable_id(relative, checksum or str(stat.st_size)),
            relative_path=relative,
            filename=path.name,
            extension=path.suffix.lower() or "[none]",
            source_group=relative.split("/", 1)[0] if "/" in relative else "[root]",
            supported=supported,
            parse_status=parse_status,
            parse_error=parse_error,
            file_size_bytes=stat.st_size,
            modified_at=datetime.fromtimestamp(stat.st_mtime, UTC).isoformat(),
            checksum=checksum,
            length_bucket=_length_bucket(metrics["character_count"]),
            **metrics,
        )

    def _content_metrics(self, content: str, image_count: int) -> dict[str, int]:
        lines = content.splitlines()
        return {
            "character_count": len(content),
            "non_whitespace_count": sum(not character.isspace() for character in content),
            "line_count": len(lines),
            "paragraph_count": len([item for item in content.split("\n\n") if item.strip()]),
            "heading_count": sum(line.lstrip().startswith("#") for line in lines),
            "table_row_count": sum(line.strip().startswith("|") for line in lines),
            "image_count": image_count,
        }

    def _summary(
        self,
        run_id: str,
        root: Path,
        records: list[InventoryRecord],
        duplicate_files: int,
    ) -> InventorySummary:
        lengths = sorted(item.character_count for item in records if item.parse_status == "parsed")
        return InventorySummary(
            run_id=run_id,
            root=str(root),
            created_at=datetime.now(UTC).isoformat(),
            total_files=len(records),
            supported_files=sum(item.supported for item in records),
            parsed_files=sum(item.parse_status == "parsed" for item in records),
            failed_files=sum(item.parse_status == "failed" for item in records),
            duplicate_files=duplicate_files,
            total_characters=sum(item.character_count for item in records),
            total_images=sum(item.image_count for item in records),
            extension_counts=dict(Counter(item.extension for item in records)),
            source_group_counts=dict(Counter(item.source_group for item in records)),
            parse_status_counts=dict(Counter(item.parse_status for item in records)),
            length_bucket_counts=dict(Counter(item.length_bucket for item in records)),
            percentiles={
                key: _percentile(lengths, value)
                for key, value in {
                    "p50": 50,
                    "p75": 75,
                    "p90": 90,
                    "p95": 95,
                    "p97": 97,
                    "p99": 99,
                }.items()
            },
        )

    def _markdown(self, summary: InventorySummary) -> str:
        lines = [
            "# 数据盘点报告",
            "",
            f"- 运行ID：`{summary.run_id}`",
            f"- 数据目录：`{summary.root}`",
            f"- 文件总数：{summary.total_files}",
            f"- 支持格式：{summary.supported_files}",
            f"- 解析成功：{summary.parsed_files}",
            f"- 解析失败：{summary.failed_files}",
            f"- 重复文件：{summary.duplicate_files}",
            f"- 总字符数：{summary.total_characters}",
            f"- 图片数：{summary.total_images}",
            "",
            "## 长度分位数",
            "",
        ]
        lines.extend(f"- {key.upper()}：{value:.0f}" for key, value in summary.percentiles.items())
        lines.extend(["", "## 长度区间", ""])
        lines.extend(f"- `{key}`：{value}" for key, value in summary.length_bucket_counts.items())
        lines.extend(["", "## 文件类型", ""])
        lines.extend(f"- `{key}`：{value}" for key, value in summary.extension_counts.items())
        lines.extend(["", "## 来源目录", ""])
        lines.extend(f"- `{key}`：{value}" for key, value in summary.source_group_counts.items())
        return "\n".join(lines) + "\n"


def _length_bucket(length: int) -> str:
    for upper_bound, name in LENGTH_BUCKETS:
        if length <= upper_bound:
            return name
    return "unknown"


def _percentile(values: list[int], percentile: int) -> float:
    if not values:
        return 0.0
    position = (len(values) - 1) * percentile / 100
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return float(values[lower])
    fraction = position - lower
    return values[lower] * (1 - fraction) + values[upper] * fraction
