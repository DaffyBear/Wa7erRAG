from app.api.dependencies import require_permission
from fastapi import APIRouter, Depends, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from rag_core.security import Permission, SecurityPrincipal

router = APIRouter(tags=["metrics"])


@router.get("/metrics", include_in_schema=False)
async def metrics(
    _: SecurityPrincipal = Depends(require_permission(Permission.AUDIT_READ)),
) -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
