from __future__ import annotations

import shutil
import uuid
from dataclasses import asdict
from pathlib import Path

from app.api.dependencies import enforce_upload_rate_limit
from app.core.config import get_settings
from app.core.container import get_container
from app.schemas.documents import IngestionResponse, VectorStatsResponse
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

router = APIRouter(prefix="/documents", tags=["documents"])


@router.post(
    "/upload",
    response_model=IngestionResponse,
    dependencies=[Depends(enforce_upload_rate_limit)],
)
async def upload_document(file: UploadFile = File(...), force: bool = False) -> IngestionResponse:
    settings = get_settings()
    suffix = Path(file.filename or "document").suffix.lower()
    if suffix not in {".docx", ".md", ".markdown", ".txt", ".html", ".htm"}:
        raise HTTPException(status_code=415, detail=f"Unsupported document type: {suffix}")
    settings.data_raw_dir.mkdir(parents=True, exist_ok=True)
    target = settings.data_raw_dir / f"{uuid.uuid4().hex}_{Path(file.filename or 'document').name}"
    with target.open("wb") as output:
        shutil.copyfileobj(file.file, output)
    try:
        result = await get_container().ingestion.ingest_path(target, force=force)
    except RuntimeError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    return IngestionResponse(**asdict(result))


@router.post(
    "/ingest-directory",
    response_model=list[IngestionResponse],
    dependencies=[Depends(enforce_upload_rate_limit)],
)
async def ingest_directory(force: bool = False) -> list[IngestionResponse]:
    results = await get_container().ingestion.ingest_directory(
        get_settings().data_raw_dir,
        force=force,
    )
    return [IngestionResponse(**asdict(result)) for result in results]


@router.get("/stats", response_model=VectorStatsResponse)
async def vector_stats() -> VectorStatsResponse:
    return VectorStatsResponse(chunk_count=await get_container().vector_store.count())
