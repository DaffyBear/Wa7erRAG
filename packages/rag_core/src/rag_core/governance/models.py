from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any


def utc_iso() -> str:
    return datetime.now(UTC).isoformat()


@dataclass(slots=True)
class InventoryRecord:
    record_id: str
    relative_path: str
    filename: str
    extension: str
    source_group: str
    supported: bool
    parse_status: str
    parse_error: str
    file_size_bytes: int
    modified_at: str
    checksum: str
    character_count: int
    non_whitespace_count: int
    line_count: int
    paragraph_count: int
    heading_count: int
    table_row_count: int
    image_count: int
    length_bucket: str
    duplicate_group: str = ""


@dataclass(slots=True)
class InventorySummary:
    run_id: str
    root: str
    created_at: str
    total_files: int
    supported_files: int
    parsed_files: int
    failed_files: int
    duplicate_files: int
    total_characters: int
    total_images: int
    extension_counts: dict[str, int]
    source_group_counts: dict[str, int]
    parse_status_counts: dict[str, int]
    length_bucket_counts: dict[str, int]
    percentiles: dict[str, float]
    records_file: str = ""


@dataclass(slots=True)
class SampleRecord:
    sample_id: str
    inventory_record_id: str
    relative_path: str
    stratum: str
    selection_order: int
    review_status: str = "pending"
    reviewer: str = ""
    reviewed_at: str = ""
    quality_score: int | None = None
    notes: str = ""
    noise_patterns: list[str] = field(default_factory=list)
    false_positive_rules: list[str] = field(default_factory=list)
    suggested_rules: list[str] = field(default_factory=list)


@dataclass(slots=True)
class CleaningDiffRecord:
    diff_id: str
    sample_id: str
    relative_path: str
    before_characters: int
    after_characters: int
    removed_characters: int
    removal_ratio: float
    before_lines: int
    after_lines: int
    removed_lines: int
    added_lines: int
    similarity_ratio: float
    rules_applied: dict[str, int]
    before_file: str
    after_file: str
    unified_diff_file: str
    html_diff_file: str
    status: str = "generated"
    error: str = ""


@dataclass(slots=True)
class GovernanceRun:
    run_id: str
    run_type: str
    created_at: str
    parameters: dict[str, Any]
    artifacts: dict[str, str]
    status: str = "completed"
    errors: list[str] = field(default_factory=list)
