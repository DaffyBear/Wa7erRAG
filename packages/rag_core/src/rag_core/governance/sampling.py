from __future__ import annotations

import csv
import json
import random
from collections import defaultdict
from dataclasses import asdict
from pathlib import Path

from rag_core.governance.models import InventoryRecord, SampleRecord
from rag_core.utils import stable_id


class StratifiedSampler:
    def sample(
        self,
        records: list[InventoryRecord],
        sample_size: int,
        seed: int = 2026,
        include_failures: bool = True,
    ) -> list[SampleRecord]:
        eligible = [
            item
            for item in records
            if item.supported and (include_failures or item.parse_status == "parsed")
        ]
        if sample_size <= 0 or not eligible:
            return []
        if sample_size >= len(eligible):
            selected = list(eligible)
        else:
            selected = self._allocate(eligible, sample_size, seed)
        return [
            SampleRecord(
                sample_id=stable_id("sample", item.record_id, str(seed)),
                inventory_record_id=item.record_id,
                relative_path=item.relative_path,
                stratum=_stratum(item),
                selection_order=index,
            )
            for index, item in enumerate(selected, start=1)
        ]

    def write_review_package(
        self,
        output_dir: Path,
        samples: list[SampleRecord],
        inventory: dict[str, InventoryRecord],
    ) -> dict[str, str]:
        output_dir.mkdir(parents=True, exist_ok=True)
        samples_json = output_dir / "review_samples.json"
        review_csv = output_dir / "review_sheet.csv"
        instructions = output_dir / "review_instructions.md"
        samples_json.write_text(
            json.dumps([asdict(item) for item in samples], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        fieldnames = [
            "sample_id",
            "relative_path",
            "stratum",
            "extension",
            "source_group",
            "character_count",
            "parse_status",
            "review_status",
            "reviewer",
            "reviewed_at",
            "quality_score",
            "notes",
            "noise_patterns",
            "false_positive_rules",
            "suggested_rules",
        ]
        with review_csv.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            for sample in samples:
                record = inventory[sample.inventory_record_id]
                writer.writerow(
                    {
                        "sample_id": sample.sample_id,
                        "relative_path": sample.relative_path,
                        "stratum": sample.stratum,
                        "extension": record.extension,
                        "source_group": record.source_group,
                        "character_count": record.character_count,
                        "parse_status": record.parse_status,
                        "review_status": sample.review_status,
                        "reviewer": sample.reviewer,
                        "reviewed_at": sample.reviewed_at,
                        "quality_score": "",
                        "notes": "",
                        "noise_patterns": "",
                        "false_positive_rules": "",
                        "suggested_rules": "",
                    }
                )
        instructions.write_text(_instructions(), encoding="utf-8")
        return {
            "samples_json": str(samples_json),
            "review_sheet_csv": str(review_csv),
            "review_instructions": str(instructions),
        }

    def import_reviews(self, review_csv: Path, samples: list[SampleRecord]) -> list[SampleRecord]:
        sample_map = {item.sample_id: item for item in samples}
        with review_csv.open("r", encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                sample = sample_map.get(row.get("sample_id", ""))
                if sample is None:
                    continue
                sample.review_status = row.get("review_status", "pending") or "pending"
                sample.reviewer = row.get("reviewer", "")
                sample.reviewed_at = row.get("reviewed_at", "")
                score = row.get("quality_score", "").strip()
                sample.quality_score = int(score) if score else None
                sample.notes = row.get("notes", "")
                sample.noise_patterns = _split_values(row.get("noise_patterns", ""))
                sample.false_positive_rules = _split_values(row.get("false_positive_rules", ""))
                sample.suggested_rules = _split_values(row.get("suggested_rules", ""))
        return list(sample_map.values())

    def _allocate(
        self,
        records: list[InventoryRecord],
        sample_size: int,
        seed: int,
    ) -> list[InventoryRecord]:
        randomizer = random.Random(seed)
        strata: dict[str, list[InventoryRecord]] = defaultdict(list)
        for record in records:
            strata[_stratum(record)].append(record)
        for group in strata.values():
            randomizer.shuffle(group)
        selected: list[InventoryRecord] = []
        ordered_strata = sorted(strata, key=lambda key: (len(strata[key]), key))
        for key in ordered_strata:
            if len(selected) >= sample_size:
                break
            selected.append(strata[key].pop())
        remaining = [item for group in strata.values() for item in group]
        randomizer.shuffle(remaining)
        selected.extend(remaining[: sample_size - len(selected)])
        randomizer.shuffle(selected)
        return selected


def _stratum(record: InventoryRecord) -> str:
    duplicate = "duplicate" if record.duplicate_group else "unique"
    return "|".join(
        [
            record.source_group,
            record.extension,
            record.length_bucket,
            record.parse_status,
            duplicate,
        ]
    )


def _split_values(value: str) -> list[str]:
    return [item.strip() for item in value.replace("；", ";").split(";") if item.strip()]


def _instructions() -> str:
    return """# 人工抽样审核说明

每个样本需要填写：

- `review_status`：`approved`、`needs_rule`、`false_positive`、`parse_failed`。
- `quality_score`：1–5分，5表示清洗结果可直接入库。
- `noise_patterns`：仍然存在的噪音，多个值使用分号分隔。
- `false_positive_rules`：误删正文的规则名称。
- `suggested_rules`：建议新增或修改的规则描述。
- `notes`：自由说明。

审核人员应同时检查清洗前文本、清洗后文本、Unified Diff 和 HTML Diff。
"""
