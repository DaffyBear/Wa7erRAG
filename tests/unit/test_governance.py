import json
from pathlib import Path

from rag_core.cleaning import RegexDocumentCleaner, default_parser_registry
from rag_core.governance import DataGovernanceService
from rag_core.governance.inventory import InventoryScanner
from rag_core.governance.sampling import StratifiedSampler


def _dataset(root: Path) -> None:
    (root / "confluence").mkdir(parents=True)
    (root / "forum").mkdir(parents=True)
    (root / "confluence" / "mqtt.md").write_text(
        "# MQTT\n\nPage ID: 123\n\n服务端口为1883。\n\n上次编辑者:张三",
        encoding="utf-8",
    )
    (root / "confluence" / "mqtt-copy.md").write_text(
        "# MQTT\n\nPage ID: 123\n\n服务端口为1883。\n\n上次编辑者:张三",
        encoding="utf-8",
    )
    (root / "forum" / "long.txt").write_text("配置说明。" * 2000, encoding="utf-8")
    (root / "unsupported.bin").write_bytes(b"binary")


def test_inventory_detects_distribution_and_duplicates(tmp_path: Path) -> None:
    _dataset(tmp_path)
    registry = default_parser_registry(tmp_path / "assets")
    summary, records = InventoryScanner(registry).scan(tmp_path, "run")
    assert summary.total_files == 4
    assert summary.parsed_files == 3
    assert summary.duplicate_files == 2
    assert summary.extension_counts[".md"] == 2
    assert summary.source_group_counts["confluence"] == 2
    assert summary.percentiles["p50"] > 0
    duplicates = [item for item in records if item.duplicate_group]
    assert len(duplicates) == 2


def test_stratified_sample_is_reproducible(tmp_path: Path) -> None:
    _dataset(tmp_path)
    registry = default_parser_registry(tmp_path / "assets")
    _, records = InventoryScanner(registry).scan(tmp_path, "run")
    sampler = StratifiedSampler()
    first = sampler.sample(records, sample_size=3, seed=42)
    second = sampler.sample(records, sample_size=3, seed=42)
    assert [item.relative_path for item in first] == [item.relative_path for item in second]
    assert len({item.stratum for item in first}) >= 2


def test_full_audit_writes_diff_and_review_package(tmp_path: Path) -> None:
    data = tmp_path / "data"
    reports = tmp_path / "reports"
    _dataset(data)
    service = DataGovernanceService(
        default_parser_registry(tmp_path / "assets"),
        RegexDocumentCleaner(),
        reports,
    )
    run = service.run_full_audit(data, sample_size=3, seed=7)
    assert Path(run.artifacts["inventory_summary_json"]).exists()
    assert Path(run.artifacts["review_review_sheet_csv"]).exists()
    assert Path(run.artifacts["cleaning_summary_json"]).exists()
    diff_summary = json.loads(
        Path(run.artifacts["cleaning_summary_json"]).read_text(encoding="utf-8")
    )
    assert diff_summary["sample_count"] == 3
    assert diff_summary["rule_hit_counts"]["confluence_page_id"] >= 1

    review_csv = Path(run.artifacts["review_review_sheet_csv"])
    text = review_csv.read_text(encoding="utf-8-sig")
    text = text.replace("pending", "approved", 1)
    review_csv.write_text(text, encoding="utf-8-sig")
    updated = service.import_review_results(run.run_id, review_csv)
    review_summary = json.loads(
        Path(updated.artifacts["review_summary"]).read_text(encoding="utf-8")
    )
    assert review_summary["reviewed_count"] >= 1

    second = service.run_full_audit(data, sample_size=3, seed=8)
    comparison = service.compare_runs(run.run_id, second.run_id)
    assert comparison.exists()
