import mimetypes

from app.core.container import get_container
from fastapi import APIRouter, HTTPException, Query, Response

router = APIRouter(prefix="/assets", tags=["assets"])


@router.get("/{object_name:path}", include_in_schema=False)
async def get_asset(
    object_name: str, signature: str = Query(min_length=64, max_length=64)
) -> Response:
    object_store = get_container().object_store
    if not object_store.verify_signature(object_name, signature):
        raise HTTPException(status_code=403, detail="Invalid asset signature")
    try:
        content = await object_store.read_bytes(object_name)
    except (FileNotFoundError, ValueError):
        raise HTTPException(status_code=404, detail="Asset not found") from None
    media_type = mimetypes.guess_type(object_name)[0] or "application/octet-stream"
    return Response(
        content, media_type=media_type, headers={"Cache-Control": "private, max-age=86400"}
    )
