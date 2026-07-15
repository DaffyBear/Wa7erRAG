from dataclasses import asdict
from pathlib import Path

from app.core.container import get_container
from app.schemas.governance import AuditRequest, AuditRunResponse, CompareRequest
from fastapi import APIRouter, File, HTTPException, UploadFile

router = APIRouter(prefix="/governance", tags=["governance"])


@router.post("/audits", response_model=AuditRunResponse)
async def run_audit(request: AuditRequest) -> AuditRunResponse:
    root = Path(request.data_root)
    if not root.exists() or not root.is_dir():
        raise HTTPException(status_code=404, detail=f"Data root not found: {root}")
    run = get_container().governance.run_full_audit(
        root,
        sample_size=request.sample_size,
        seed=request.seed,
        include_failures=request.include_failures,
    )
    return AuditRunResponse(**asdict(run))


@router.get("/audits", response_model=list[AuditRunResponse])
async def list_audits() -> list[AuditRunResponse]:
    return [AuditRunResponse(**asdict(item)) for item in get_container().governance.list_runs()]


@router.get("/audits/{run_id}", response_model=AuditRunResponse)
async def get_audit(run_id: str) -> AuditRunResponse:
    try:
        run = get_container().governance.load_run(run_id)
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=f"Audit run not found: {run_id}") from error
    return AuditRunResponse(**asdict(run))


@router.post("/audits/{run_id}/reviews", response_model=AuditRunResponse)
async def import_review(run_id: str, file: UploadFile = File(...)) -> AuditRunResponse:
    target = get_container().governance.reports_root / run_id / "review" / "review_sheet_import.csv"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(await file.read())
    try:
        run = get_container().governance.import_review_results(run_id, target)
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=f"Audit run not found: {run_id}") from error
    return AuditRunResponse(**asdict(run))


@router.post("/comparisons")
async def compare_audits(request: CompareRequest) -> dict[str, str]:
    try:
        output = get_container().governance.compare_runs(
            request.baseline_run_id,
            request.current_run_id,
        )
    except FileNotFoundError as error:
        raise HTTPException(
            status_code=404, detail="One or more audit runs were not found"
        ) from error
    return {"comparison_file": str(output)}
