from __future__ import annotations

import re
from dataclasses import dataclass

from rag_core.models import Document
from rag_core.utils import normalize_whitespace


@dataclass(frozen=True, slots=True)
class CleaningRule:
    name: str
    pattern: str
    replacement: str = ""


DEFAULT_RULES = [
    CleaningRule("confluence_page_id", r"(?im)^\s*(?:confluence\s*)?page\s*id\s*[:：]\s*\d+\s*$"),
    CleaningRule("last_editor", r"(?im)^\s*上次编辑者\s*[:：].*$"),
    CleaningRule("browser_video_warning", r"(?im)^\s*您的浏览器不支\s*:?\s*持\s*video\s*标签\s*$"),
    CleaningRule("upload_timestamp", r"(?im)^\s*(?:上传|创建|更新时间)\s*[:：].*$"),
    CleaningRule("download_count", r"(?im)^\s*下载次数\s*[:：]\s*\d+\s*$"),
    CleaningRule("forum_reply_marker", r"(?im)^\s*(?:回复|只看楼主|楼层)\s*[:：#]?\s*\d*\s*$"),
    CleaningRule("attachment_hint", r"(?im)^\s*(?:附件|点击下载附件)\s*[:：].*$"),
    CleaningRule("pure_number_line", r"(?m)^\s*\d+\s*$"),
]


class RegexDocumentCleaner:
    def __init__(self, rules: list[CleaningRule] | None = None) -> None:
        self.rules = rules or DEFAULT_RULES
        self.compiled = [(rule, re.compile(rule.pattern)) for rule in self.rules]

    def clean(self, document: Document) -> Document:
        content = document.content
        applied: dict[str, int] = {}
        for rule, pattern in self.compiled:
            content, count = pattern.subn(rule.replacement, content)
            if count:
                applied[rule.name] = count
        content = normalize_whitespace(content)
        document.content = content
        document.metadata["cleaning_rules_applied"] = applied
        document.metadata["cleaned_length"] = len(content)
        return document
