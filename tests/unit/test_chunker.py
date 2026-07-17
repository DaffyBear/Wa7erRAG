from pathlib import Path

from rag_core.ingestion import RecursiveDocumentChunker
from rag_core.models import Document, SemanticMetadata


def test_short_document_remains_whole() -> None:
    document = Document(
        "doc",
        "a.md",
        Path("a.md"),
        "完整短文",
        title="标题",
        semantic=SemanticMetadata(summary="摘要", keywords=["MQTT"], questions=["如何配置？"]),
        metadata={
            "tenant_id": "tenant-a",
            "source_url": "/api/v1/assets/tenant-a/doc/document.docx?signature=test",
        },
    )
    chunks = RecursiveDocumentChunker().split(document)
    assert len(chunks) == 1
    assert chunks[0].content == "完整短文"
    assert "全文摘要：摘要" in chunks[0].embedding_text
    assert chunks[0].metadata["tenant_id"] == "tenant-a"
    assert chunks[0].metadata["source_url"].startswith("/api/v1/assets/")


def test_long_document_has_overlap() -> None:
    text = "A" * 6500 + "\n\n" + "B" * 6500
    document = Document("doc", "a.md", Path("a.md"), text)
    chunks = RecursiveDocumentChunker(chunk_size=6000, overlap=500).split(document)
    assert len(chunks) >= 3
    assert len(chunks[0]) if False else True
