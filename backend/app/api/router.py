from fastapi import APIRouter

from app.api.diagnostics import router as diagnostics_router
from app.api.health import router as health_router

api_router = APIRouter()
api_router.include_router(health_router)
api_router.include_router(diagnostics_router)
