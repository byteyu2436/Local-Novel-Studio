from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.adapters.sqlite import bootstrap_local_runtime
from app.api.router import api_router
from app.settings import get_settings


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    settings, engine, session_factory = bootstrap_local_runtime()
    application.state.settings = settings
    application.state.engine = engine
    application.state.session_factory = session_factory
    yield
    engine.dispose()


def create_app() -> FastAPI:
    settings = get_settings()
    application = FastAPI(
        title="Local Novel Studio",
        version="0.1.0",
        description="Open-source, local-first novel continuation tool.",
        lifespan=lifespan,
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_origins),
        allow_credentials=False,
        allow_methods=["GET"],
        allow_headers=["*"],
    )
    application.include_router(api_router)
    return application


app = create_app()
