from fastapi import APIRouter, Request

from app.adapters.milvus import MilvusHealthAdapter
from app.adapters.ollama import OllamaAdapter
from app.schemas.diagnostics import DiagnosticsResponse
from app.services.diagnostics import collect_diagnostics

router = APIRouter(prefix="/api/system", tags=["system"])


@router.get("/diagnostics", response_model=DiagnosticsResponse)
async def diagnostics(request: Request) -> DiagnosticsResponse:
    settings = request.app.state.settings
    ollama = OllamaAdapter(settings)
    milvus = MilvusHealthAdapter(settings)
    try:
        ollama_health = await ollama.health()
        milvus_health = await milvus.health()
        return await collect_diagnostics(
            settings=settings,
            engine=request.app.state.engine,
            ollama_health=ollama_health,
            milvus_health=milvus_health,
        )
    finally:
        await ollama.aclose()
