import httpx

from app.adapters.milvus.types import MilvusHealth
from app.settings import Settings


class MilvusHealthAdapter:
    """Health-only adapter. Collection schema and embeddings come later."""

    def __init__(self, settings: Settings, *, client: httpx.AsyncClient | None = None) -> None:
        self._settings = settings
        self._client = client

    @property
    def health_url(self) -> str:
        return f"http://{self._settings.milvus_host}:{self._settings.milvus_health_port}/healthz"

    async def health(self) -> MilvusHealth:
        hint = (
            "Start Milvus with scripts/milvus-up.ps1. Milvus stores a rebuildable vector index, "
            "not Canon; deleting the container volumes does not delete SQLite truth."
        )
        try:
            if self._client is None:
                async with httpx.AsyncClient(timeout=3.0) as client:
                    response = await client.get(self.health_url)
            else:
                response = await self._client.get(self.health_url)
        except httpx.HTTPError:
            return MilvusHealth(
                reachable=False,
                status="unavailable",
                host=self._settings.milvus_host,
                port=self._settings.milvus_port,
                health_url=self.health_url,
                message=(
                    f"Milvus is not reachable at {self._settings.milvus_host}:"
                    f"{self._settings.milvus_port} (health {self.health_url})."
                ),
                hint=hint,
            )

        if response.is_success:
            return MilvusHealth(
                reachable=True,
                status="ok",
                host=self._settings.milvus_host,
                port=self._settings.milvus_port,
                health_url=self.health_url,
                message="Milvus healthz returned OK.",
            )

        return MilvusHealth(
            reachable=False,
            status="unavailable",
            host=self._settings.milvus_host,
            port=self._settings.milvus_port,
            health_url=self.health_url,
            message=f"Milvus healthz returned HTTP {response.status_code}.",
            hint=hint,
        )
