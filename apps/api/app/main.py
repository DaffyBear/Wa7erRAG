import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.core.config import get_settings
from app.core.container import get_container


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    settings.data_raw_dir.mkdir(parents=True, exist_ok=True)
    settings.data_processed_dir.mkdir(parents=True, exist_ok=True)
    (settings.data_asset_dir / "public").mkdir(parents=True, exist_ok=True)
    container = get_container()
    if not settings.rag_use_mocks and hasattr(container.traces, "create_schema"):
        await container.traces.create_schema()
    await container.security.repository.create_schema()
    yield
    if container.redis_backend is not None:
        await container.redis_backend.close()


settings = get_settings()
app = FastAPI(title=settings.app_name, version="0.2.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(api_router, prefix="/api/v1")


@app.middleware("http")
async def request_security_audit(request: Request, call_next):
    request_id = request.headers.get("x-request-id") or uuid.uuid4().hex
    request.state.request_id = request_id
    started = time.perf_counter()
    response = None
    outcome = "success"
    try:
        response = await call_next(request)
        if response.status_code >= 400:
            outcome = "denied" if response.status_code in (401, 403) else "failure"
        return response
    except Exception:
        outcome = "error"
        raise
    finally:
        response_status = response.status_code if response is not None else 500
        principal = getattr(request.state, "principal", None)
        forwarded = request.headers.get("x-forwarded-for", "").split(",")[0].strip()
        client_ip = forwarded or (request.client.host if request.client else "unknown")
        try:
            await get_container().security.audit(
                principal,
                action=f"http.{request.method.lower()}",
                resource_type="http_endpoint",
                resource_id=request.url.path,
                outcome=outcome,
                ip_address=client_ip,
                user_agent=request.headers.get("user-agent", ""),
                request_id=request_id,
                details={
                    "status_code": response_status,
                    "duration_ms": round((time.perf_counter() - started) * 1000, 3),
                    "query_keys": sorted(request.query_params.keys()),
                },
            )
        except Exception:
            pass
        if response is not None:
            response.headers["X-Request-ID"] = request_id
