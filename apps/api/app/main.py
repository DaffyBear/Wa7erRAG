from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

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
settings.data_asset_dir.mkdir(parents=True, exist_ok=True)
app.mount(
    "/assets",
    StaticFiles(directory=settings.data_asset_dir / "public", check_dir=False),
    name="assets",
)
app.include_router(api_router, prefix="/api/v1")
