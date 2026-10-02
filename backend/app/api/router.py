from fastapi import APIRouter

from app.api.analysis import router as analysis_router
from app.api.diagnostics import router as diagnostics_router
from app.api.health import router as health_router
from app.api.imports import router as imports_router
from app.api.initialization import router as initialization_router
from app.api.memory import router as memory_router
from app.api.reader import router as reader_router
from app.api.retrieval import router as retrieval_router
from app.api.sqlite import router as sqlite_router
from app.api.writing import router as writing_router

api_router = APIRouter()
api_router.include_router(health_router)
api_router.include_router(sqlite_router)
api_router.include_router(diagnostics_router)
api_router.include_router(imports_router)
api_router.include_router(memory_router)
api_router.include_router(reader_router)
api_router.include_router(retrieval_router)
api_router.include_router(initialization_router)
api_router.include_router(analysis_router)
api_router.include_router(writing_router)
