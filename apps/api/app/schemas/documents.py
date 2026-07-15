from pydantic import BaseModel


class IngestionResponse(BaseModel):
    document_id: str
    filename: str
    chunk_count: int
    skipped: bool
    output_markdown: str
    output_docx: str


class VectorStatsResponse(BaseModel):
    chunk_count: int
