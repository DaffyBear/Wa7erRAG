from dataclasses import asdict
from pathlib import Path

from app.api.dependencies import require_permission
from app.core.container import get_container
from app.schemas.governance import AuditRequest, AuditRunResponse, CompareRequest
from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from rag_core.security import Permission, SecurityPrincipal

router = APIRouter(prefix="/governance", tags=["governance"])


@router.post("/audits", response_model=AuditRunResponse)
async def run_audit(
    body: AuditRequest,
    request: Request,
    principal: SecurityPrincipal = Depends(require_permission(Permission.GOVERNANCE_WRITE)),
) -> AuditRunResponse:
    root = Path(body.data_root)
    if not root.exists() or not root.is_dir():
        raise HTTPException(status_code=404, detail=f"Data root not found: {root}")
    run = get_container().governance.run_full_audit(
        root, body.sample_size, body.seed, body.include_failures, principal.tenant_id
    )
    await _audit(request, principal, "governance.run", run.run_id)
    return AuditRunResponse(**asdict(run))


@router.get("/audits", response_model=list[AuditRunResponse])
async def list_audits(
    principal: SecurityPrincipal = Depends(require_permission(Permission.GOVERNANCE_READ)),
) -> list[AuditRunResponse]:
    return [
        AuditRunResponse(**asdict(item))
        for item in get_container().governance.list_runs(principal.tenant_id)
    ]


@router.get("/audits/{run_id}", response_model=AuditRunResponse)
async def get_audit(
    run_id: str,
    principal: SecurityPrincipal = Depends(require_permission(Permission.GOVERNANCE_READ)),
) -> AuditRunResponse:
    try:
        run = get_container().governance.load_run(run_id, principal.tenant_id)
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=f"Audit run not found: {run_id}") from error
    return AuditRunResponse(**asdict(run))


@router.post("/audits/{run_id}/reviews", response_model=AuditRunResponse)
async def import_review(
    run_id: str,
    request: Request,
    file: UploadFile = File(...),
    principal: SecurityPrincipal = Depends(require_permission(Permission.GOVERNANCE_WRITE)),
) -> AuditRunResponse:
    target = (
        get_container().governance.tenant_reports_root(principal.tenant_id)
        / run_id
        / "review"
        / "review_sheet_import.csv"
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(await file.read())
    try:
        run = get_container().governance.import_review_results(run_id, target, principal.tenant_id)
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=f"Audit run not found: {run_id}") from error
    await _audit(request, principal, "governance.review_import", run_id)
    return AuditRunResponse(**asdict(run))


@router.post("/comparisons")
async def compare_audits(
    body: CompareRequest,
    request: Request,
    principal: SecurityPrincipal = Depends(require_permission(Permission.GOVERNANCE_WRITE)),
) -> dict[str, str]:
    try:
        output = get_container().governance.compare_runs(
            body.baseline_run_id, body.current_run_id, principal.tenant_id
        )
    except FileNotFoundError as error:
        raise HTTPException(
            status_code=404, detail="One or more audit runs were not found"
        ) from error
    await _audit(
        request,
        principal,
        "governance.compare",
        "comparison",
        {"baseline": body.baseline_run_id, "current": body.current_run_id},
    )
    return {"comparison_file": str(output)}


async def _audit(
    request: Request,
    principal: SecurityPrincipal,
    action: str,
    resource_id: str,
    details: dict | None = None,
) -> None:
    await get_container().security.audit(
        principal,
        action,
        "governance_run",
        resource_id,
        request_id=request.state.request_id,
        details=details,
    )
