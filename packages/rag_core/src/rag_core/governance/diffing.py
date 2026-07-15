from __future__ import annotations

import csv
import difflib
import html
import json
from collections import Counter
from dataclasses import asdict
from pathlib import Path
from typing import Any

from rag_core.governance.models import CleaningDiffRecord, InventoryRecord, SampleRecord
from rag_core.utils import stable_id


class CleaningDiffReporter:
    def __init__(self, parser_registry: Any, cleaner: Any) -> None:
        self.parser_registry = parser_registry
        self.cleaner = cleaner

    def generate(
        self,
        data_root: Path,
        output_dir: Path,
        samples: list[SampleRecord],
        inventory: dict[str, InventoryRecord],
    ) -> tuple[list[CleaningDiffRecord], dict[str, Any]]:
        output_dir.mkdir(parents=True, exist_ok=True)
        records: list[CleaningDiffRecord] = []
        for sample in samples:
            record = inventory[sample.inventory_record_id]
            records.append(self._generate_one(data_root, output_dir, sample, record))
        summary = self._summary(records, samples)
        artifacts = self._write_reports(output_dir, records, summary)
        summary["artifacts"] = artifacts
        return records, summary

    def _generate_one(
        self,
        data_root: Path,
        output_dir: Path,
        sample: SampleRecord,
        inventory: InventoryRecord,
    ) -> CleaningDiffRecord:
        sample_dir = output_dir / "samples" / sample.sample_id
        sample_dir.mkdir(parents=True, exist_ok=True)
        before_path = sample_dir / "before.md"
        after_path = sample_dir / "after.md"
        unified_path = sample_dir / "cleaning.diff"
        html_path = sample_dir / "cleaning_diff.html"
        source = data_root / inventory.relative_path
        try:
            document = self.parser_registry.parse(source)
            before = document.content
            cleaned = self.cleaner.clean(document)
            after = cleaned.content
            before_lines = before.splitlines(keepends=True)
            after_lines = after.splitlines(keepends=True)
            unified = "".join(
                difflib.unified_diff(
                    before_lines,
                    after_lines,
                    fromfile=f"before/{inventory.relative_path}",
                    tofile=f"after/{inventory.relative_path}",
                )
            )
            html_diff = difflib.HtmlDiff(wrapcolumn=120).make_file(
                before.splitlines(),
                after.splitlines(),
                fromdesc=html.escape(f"清洗前：{inventory.relative_path}"),
                todesc=html.escape(f"清洗后：{inventory.relative_path}"),
                context=True,
                numlines=3,
                charset="utf-8",
            )
            before_path.write_text(before, encoding="utf-8")
            after_path.write_text(after, encoding="utf-8")
            unified_path.write_text(unified, encoding="utf-8")
            html_path.write_text(html_diff, encoding="utf-8")
            removed_lines, added_lines = _line_change_counts(unified)
            removed_characters = max(len(before) - len(after), 0)
            removal_ratio = removed_characters / max(len(before), 1)
            similarity = difflib.SequenceMatcher(None, before, after, autojunk=False).ratio()
            status = "generated"
            if removal_ratio >= 0.5:
                status = "high_removal_warning"
            elif not cleaned.metadata.get("cleaning_rules_applied"):
                status = "no_rule_match"
            return CleaningDiffRecord(
                diff_id=stable_id("diff", sample.sample_id),
                sample_id=sample.sample_id,
                relative_path=inventory.relative_path,
                before_characters=len(before),
                after_characters=len(after),
                removed_characters=removed_characters,
                removal_ratio=round(removal_ratio, 6),
                before_lines=len(before.splitlines()),
                after_lines=len(after.splitlines()),
                removed_lines=removed_lines,
                added_lines=added_lines,
                similarity_ratio=round(similarity, 6),
                rules_applied=cleaned.metadata.get("cleaning_rules_applied", {}),
                before_file=str(before_path),
                after_file=str(after_path),
                unified_diff_file=str(unified_path),
                html_diff_file=str(html_path),
                status=status,
            )
        except Exception as error:
            return CleaningDiffRecord(
                diff_id=stable_id("diff", sample.sample_id),
                sample_id=sample.sample_id,
                relative_path=inventory.relative_path,
                before_characters=0,
                after_characters=0,
                removed_characters=0,
                removal_ratio=0.0,
                before_lines=0,
                after_lines=0,
                removed_lines=0,
                added_lines=0,
                similarity_ratio=0.0,
                rules_applied={},
                before_file=str(before_path),
                after_file=str(after_path),
                unified_diff_file=str(unified_path),
                html_diff_file=str(html_path),
                status="failed",
                error=f"{type(error).__name__}: {error}"[:1000],
            )

    def _summary(
        self,
        records: list[CleaningDiffRecord],
        samples: list[SampleRecord],
    ) -> dict[str, Any]:
        rule_hits: Counter[str] = Counter()
        for record in records:
            rule_hits.update(record.rules_applied)
        reviewed = [item for item in samples if item.review_status != "pending"]
        scores = [item.quality_score for item in reviewed if item.quality_score is not None]
        return {
            "sample_count": len(records),
            "generated_count": sum(item.status != "failed" for item in records),
            "failed_count": sum(item.status == "failed" for item in records),
            "high_removal_warning_count": sum(
                item.status == "high_removal_warning" for item in records
            ),
            "no_rule_match_count": sum(item.status == "no_rule_match" for item in records),
            "average_removal_ratio": round(
                sum(item.removal_ratio for item in records) / max(len(records), 1),
                6,
            ),
            "average_similarity_ratio": round(
                sum(item.similarity_ratio for item in records) / max(len(records), 1),
                6,
            ),
            "rule_hit_counts": dict(rule_hits.most_common()),
            "reviewed_count": len(reviewed),
            "approved_count": sum(item.review_status == "approved" for item in reviewed),
            "needs_rule_count": sum(item.review_status == "needs_rule" for item in reviewed),
            "false_positive_count": sum(
                item.review_status == "false_positive" for item in reviewed
            ),
            "average_quality_score": round(sum(scores) / len(scores), 3) if scores else None,
            "noise_pattern_counts": dict(
                Counter(pattern for item in reviewed for pattern in item.noise_patterns)
            ),
            "false_positive_rule_counts": dict(
                Counter(rule for item in reviewed for rule in item.false_positive_rules)
            ),
            "suggested_rule_counts": dict(
                Counter(rule for item in reviewed for rule in item.suggested_rules)
            ),
        }

    def _write_reports(
        self,
        output_dir: Path,
        records: list[CleaningDiffRecord],
        summary: dict[str, Any],
    ) -> dict[str, str]:
        records_json = output_dir / "cleaning_diff_records.json"
        records_csv = output_dir / "cleaning_diff_records.csv"
        summary_json = output_dir / "cleaning_diff_summary.json"
        summary_md = output_dir / "cleaning_diff_summary.md"
        records_json.write_text(
            json.dumps([asdict(item) for item in records], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        with records_csv.open("w", encoding="utf-8-sig", newline="") as handle:
            fieldnames = list(asdict(records[0]).keys()) if records else []
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            if records:
                writer.writeheader()
                for item in records:
                    row = asdict(item)
                    row["rules_applied"] = json.dumps(row["rules_applied"], ensure_ascii=False)
                    writer.writerow(row)
        summary_json.write_text(
            json.dumps(summary, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        summary_md.write_text(_summary_markdown(summary), encoding="utf-8")
        return {
            "records_json": str(records_json),
            "records_csv": str(records_csv),
            "summary_json": str(summary_json),
            "summary_markdown": str(summary_md),
        }


def _line_change_counts(unified_diff: str) -> tuple[int, int]:
    removed = 0
    added = 0
    for line in unified_diff.splitlines():
        if line.startswith("---") or line.startswith("+++"):
            continue
        if line.startswith("-"):
            removed += 1
        elif line.startswith("+"):
            added += 1
    return removed, added


def _summary_markdown(summary: dict[str, Any]) -> str:
    lines = [
        "# 清洗差异汇总",
        "",
        f"- 样本数：{summary['sample_count']}",
        f"- 成功生成：{summary['generated_count']}",
        f"- 生成失败：{summary['failed_count']}",
        f"- 高删除比例警告：{summary['high_removal_warning_count']}",
        f"- 未命中规则：{summary['no_rule_match_count']}",
        f"- 平均删除比例：{summary['average_removal_ratio']:.2%}",
        f"- 平均文本相似度：{summary['average_similarity_ratio']:.2%}",
        f"- 已审核：{summary['reviewed_count']}",
        f"- 审核通过：{summary['approved_count']}",
        f"- 需要新增规则：{summary['needs_rule_count']}",
        f"- 疑似误删：{summary['false_positive_count']}",
        "",
        "## 规则命中次数",
        "",
    ]
    lines.extend(f"- `{key}`：{value}" for key, value in summary["rule_hit_counts"].items())
    lines.extend(["", "## 审核发现的残留噪音", ""])
    lines.extend(f"- `{key}`：{value}" for key, value in summary["noise_pattern_counts"].items())
    lines.extend(["", "## 疑似误删规则", ""])
    lines.extend(
        f"- `{key}`：{value}" for key, value in summary["false_positive_rule_counts"].items()
    )
    lines.extend(["", "## 建议新增规则", ""])
    lines.extend(f"- `{key}`：{value}" for key, value in summary["suggested_rule_counts"].items())
    return "\n".join(lines) + "\n"
