from pathlib import Path

from rag_core.cleaning import RegexDocumentCleaner
from rag_core.models import Document


def test_cleaner_removes_known_noise() -> None:
    document = Document(
        "1", "test.md", Path("test.md"), "Page ID: 123\n正文内容\n上次编辑者:张三\n99"
    )
    cleaned = RegexDocumentCleaner().clean(document)
    assert cleaned.content == "正文内容"
    assert cleaned.metadata["cleaning_rules_applied"]["confluence_page_id"] == 1



def test_cleaner_removes_xml_incompatible_control_characters() -> None:
    document = Document("doc", "paper.pdf", Path("paper.pdf"), "valid\x00text\x0bbody\uffff")
    cleaned = RegexDocumentCleaner().clean(document)
    assert cleaned.content == "validtextbody"
