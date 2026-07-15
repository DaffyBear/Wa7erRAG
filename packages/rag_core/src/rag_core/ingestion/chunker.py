from __future__ import annotations

from rag_core.models import Document, DocumentChunk
from rag_core.utils import stable_id


class RecursiveDocumentChunker:
    separators = ("\n# ", "\n## ", "\n\n", "\n", "。", "；", "，", " ")

    def __init__(
        self,
        short_document_limit: int = 6000,
        chunk_size: int = 6000,
        overlap: int = 500,
    ) -> None:
        if overlap >= chunk_size:
            raise ValueError("chunk overlap must be smaller than chunk size")
        self.short_document_limit = short_document_limit
        self.chunk_size = chunk_size
        self.overlap = overlap

    def split(self, document: Document) -> list[DocumentChunk]:
        contents = (
            [document.content]
            if len(document.content) <= self.short_document_limit
            else self._split(document.content)
        )
        prefix = self._prefix(document)
        return [
            DocumentChunk(
                chunk_id=stable_id(document.document_id, str(index)),
                document_id=document.document_id,
                filename=document.filename,
                chunk_index=index,
                content=content,
                embedding_text=f"{prefix}\n\n{content}".strip(),
                metadata={
                    "title": document.title,
                    "summary": document.semantic.summary,
                    "keywords": document.semantic.keywords,
                    "questions": document.semantic.questions,
                    "source_path": str(document.source_path),
                    "checksum": document.checksum,
                },
            )
            for index, content in enumerate(contents)
        ]

    def _prefix(self, document: Document) -> str:
        keywords = "、".join(document.semantic.keywords)
        questions = "；".join(document.semantic.questions)
        return (
            f"文档标题：{document.title}\n"
            f"全文摘要：{document.semantic.summary}\n"
            f"关键词：{keywords}\n"
            f"可回答问题：{questions}"
        )

    def _split(self, text: str) -> list[str]:
        chunks: list[str] = []
        start = 0
        while start < len(text):
            hard_end = min(start + self.chunk_size, len(text))
            end = hard_end
            if hard_end < len(text):
                search_start = start + max(self.chunk_size // 2, 1)
                best = -1
                for separator in self.separators:
                    position = text.rfind(separator, search_start, hard_end)
                    best = max(
                        best,
                        position + len(separator) if position >= 0 else -1,
                    )
                if best > start:
                    end = best
            chunk = text[start:end].strip()
            if chunk:
                chunks.append(chunk)
            if end >= len(text):
                break
            start = max(end - self.overlap, start + 1)
        return chunks
