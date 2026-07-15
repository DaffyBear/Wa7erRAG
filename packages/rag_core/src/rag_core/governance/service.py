from __future__ import annotations

import json
import uuid
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from rag_core.governance.diffing import CleaningDiffReporter
from rag_core.governance.inventory import InventoryScanner
from rag_core.governance.models import GovernanceRun, InventoryRecord, SampleRecord
from rag_core.governance.sampling import StratifiedSampler


class DataGovernanceService:
    def __init__(
        self,
        parser_registry: Any,
        cleaner: Any,
        reports_root: Path,
    ) -> None:
        self.inventory_scanner = InventoryScanner(parser_registry)
        self.sampler = StratifiedSampler()
        self.diff_reporter = CleaningDiffReporter(parser_registry, cleaner)
        self.reports_root = reports_root

    def run_full_audit(
        self,
        data_root: Path,
        sample_size: int = 50,
        seed: int = 2026,
        include_failures: bool = True,
    ) -> GovernanceRun:
        run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
        run_dir = self.reports_root / run_id
        inventory_dir = run_dir / "inventory"
        review_dir = run_dir / "review"
        diff_dir = run_dir / "cleaning_diff"
        summary, records = self.inventory_scanner.scan(data_root, run_id)
        inventory_artifacts = self.inventory_scanner.write_reports(
            inventory_dir,
            summary,
            records,
        )
        samples = self.sampler.sample(records, sample_size, seed, include_failures)
        inventory_map = {item.record_id: item for item in records}
        review_artifacts = self.sampler.write_review_package(
            review_dir,
            samples,
            inventory_map,
        )
        _, diff_summary = self.diff_reporter.generate(
            data_root,
            diff_dir,
            samples,
            inventory_map,
        )
        diff_artifacts = diff_summary.pop("artifacts")
        artifacts = (
            {f"inventory_{key}": value for key, value in inventory_artifacts.items()}
            | {f"review_{key}": value for key, value in review_artifacts.items()}
            | {f"cleaning_{key}": value for key, value in diff_artifacts.items()}
        )
        overview = self._write_overview(
            run_dir,
            summary=asdict(summary),
            diff_summary=diff_summary,
            sample_size=len(samples),
        )
        artifacts["overview"] = str(overview)
        run = GovernanceRun(
            run_id=run_id,
            run_type="full_audit",
            created_at=datetime.now(UTC).isoformat(),
            parameters={
                "data_root": str(data_root.resolve()),
                "sample_size": sample_size,
                "seed": seed,
                "include_failures": include_failures,
            },
            artifacts=artifacts,
        )
        self._write_manifest(run_dir, run)
        self._update_latest(run_dir)
        return run

    def import_review_results(self, run_id: str, review_csv: Path) -> GovernanceRun:
        run_dir = self.reports_root / run_id
        run = self.load_run(run_id)
        samples_path = Path(run.artifacts["review_samples_json"])
        samples = [
            SampleRecord(**item) for item in json.loads(samples_path.read_text(encoding="utf-8"))
        ]
        updated = self.sampler.import_reviews(review_csv, samples)
        samples_path.write_text(
            json.dumps([asdict(item) for item in updated], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        records = self._load_inventory(run)
        inventory_map = {item.record_id: item for item in records}
        data_root = Path(run.parameters["data_root"])
        _, diff_summary = self.diff_reporter.generate(
            data_root,
            run_dir / "cleaning_diff",
            updated,
            inventory_map,
        )
        run.artifacts.update(
            {f"cleaning_{key}": value for key, value in diff_summary.pop("artifacts").items()}
        )
        review_summary = run_dir / "review" / "review_summary.json"
        review_summary.write_text(
            json.dumps(diff_summary, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        run.artifacts["review_summary"] = str(review_summary)
        self._write_manifest(run_dir, run)
        return run

    def compare_runs(self, baseline_run_id: str, current_run_id: str) -> Path:
        baseline = self.load_run(baseline_run_id)
        current = self.load_run(current_run_id)
        baseline_summary = json.loads(
            Path(baseline.artifacts["inventory_summary_json"]).read_text(encoding="utf-8")
        )
        current_summary = json.loads(
            Path(current.artifacts["inventory_summary_json"]).read_text(encoding="utf-8")
        )
        baseline_diff = json.loads(
            Path(baseline.artifacts["inventory_summary_json"])
            .parent.parent.joinpath("cleaning_diff", "cleaning_diff_summary.json")
            .read_text(encoding="utf-8")
        )
        current_diff = json.loads(
            Path(current.artifacts["inventory_summary_json"])
            .parent.parent.joinpath("cleaning_diff", "cleaning_diff_summary.json")
            .read_text(encoding="utf-8")
        )
        comparison = {
            "baseline_run_id": baseline_run_id,
            "current_run_id": current_run_id,
            "inventory": {
                key: {
                    "baseline": baseline_summary.get(key),
                    "current": current_summary.get(key),
                    "delta": _numeric_delta(baseline_summary.get(key), current_summary.get(key)),
                }
                for key in [
                    "total_files",
                    "parsed_files",
                    "failed_files",
                    "duplicate_files",
                    "total_characters",
                    "total_images",
                ]
            },
            "cleaning": {
                key: {
                    "baseline": baseline_diff.get(key),
                    "current": current_diff.get(key),
                    "delta": _numeric_delta(baseline_diff.get(key), current_diff.get(key)),
                }
                for key in [
                    "failed_count",
                    "high_removal_warning_count",
                    "no_rule_match_count",
                    "average_removal_ratio",
                    "average_similarity_ratio",
                    "approved_count",
                    "needs_rule_count",
                    "false_positive_count",
                    "average_quality_score",
                ]
            },
        }
        output = self.reports_root / current_run_id / f"comparison_vs_{baseline_run_id}.json"
        output.write_text(json.dumps(comparison, ensure_ascii=False, indent=2), encoding="utf-8")
        return output

    def load_run(self, run_id: str) -> GovernanceRun:
        manifest = self.reports_root / run_id / "run_manifest.json"
        return GovernanceRun(**json.loads(manifest.read_text(encoding="utf-8")))

    def list_runs(self) -> list[GovernanceRun]:
        runs = []
        if not self.reports_root.exists():
            return runs
        for manifest in sorted(self.reports_root.glob("*/run_manifest.json"), reverse=True):
            runs.append(GovernanceRun(**json.loads(manifest.read_text(encoding="utf-8"))))
        return runs

    def _load_inventory(self, run: GovernanceRun) -> list[InventoryRecord]:
        values = json.loads(
            Path(run.artifacts["inventory_records_json"]).read_text(encoding="utf-8")
        )
        return [InventoryRecord(**item) for item in values]

    def _write_manifest(self, run_dir: Path, run: GovernanceRun) -> None:
        manifest = run_dir / "run_manifest.json"
        manifest.write_text(json.dumps(asdict(run), ensure_ascii=False, indent=2), encoding="utf-8")
        run.artifacts["manifest"] = str(manifest)
        manifest.write_text(json.dumps(asdict(run), ensure_ascii=False, indent=2), encoding="utf-8")

    def _update_latest(self, run_dir: Path) -> None:
        latest = self.reports_root / "latest.txt"
        latest.parent.mkdir(parents=True, exist_ok=True)
        latest.write_text(run_dir.name, encoding="utf-8")

    def _write_overview(
        self,
        run_dir: Path,
        summary: dict[str, Any],
        diff_summary: dict[str, Any],
        sample_size: int,
    ) -> Path:
        output = run_dir / "overview.md"
        output.write_text(
            "\n".join(
                [
                    "# 数据治理运行总览",
                    "",
                    f"- 文件总数：{summary['total_files']}",
                    f"- 解析成功：{summary['parsed_files']}",
                    f"- 解析失败：{summary['failed_files']}",
                    f"- 重复文件：{summary['duplicate_files']}",
                    f"- 抽样数量：{sample_size}",
                    f"- 平均清洗删除比例：{diff_summary['average_removal_ratio']:.2%}",
                    f"- 高删除比例警告：{diff_summary['high_removal_warning_count']}",
                    f"- 未命中清洗规则：{diff_summary['no_rule_match_count']}",
                    "",
                    "详细报告位于 `inventory`、`review` 和 `cleaning_diff` 子目录。",
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        return output


def _numeric_delta(baseline: Any, current: Any) -> float | int | None:
    if isinstance(baseline, (int, float)) and isinstance(current, (int, float)):
        return current - baseline
    return None
