from app.api.routes import assets, chat, documents, feedback, governance, health, metrics, security
from fastapi import APIRouter

api_router = APIRouter()
api_router.include_router(assets.router)
api_router.include_router(health.router)
api_router.include_router(chat.router)
api_router.include_router(documents.router)
api_router.include_router(feedback.router)
api_router.include_router(metrics.router)
api_router.include_router(governance.router)

api_router.include_router(security.router)
