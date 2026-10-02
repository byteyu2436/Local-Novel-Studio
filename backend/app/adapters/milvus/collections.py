import json
from dataclasses import dataclass

import httpx

from app.domain.milvus_collection import (
    COLLECTION_FIELDS,
    CollectionSpec,
    IndexParameterProfile,
    MilvusCollectionError,
)
from app.settings import Settings


@dataclass(frozen=True)
class CollectionDescription:
    name: str
    dimension: int
    field_names: tuple[str, ...]
    metadata: dict[str, str]
    index: IndexParameterProfile


@dataclass(frozen=True)
class DenseHit:
    chunk_id: str
    novel_id: str
    chapter_id: str
    score: float
    text_hash: str
    canon_status: str


class MilvusCollectionClient:
    """Local Milvus collection lifecycle. It does not store Canon text."""

    def __init__(self, settings: Settings, *, client: httpx.AsyncClient | None = None) -> None:
        self._settings = settings
        self._client = client
        self._owns_client = client is None

    @property
    def base_url(self) -> str:
        return f"http://{self._settings.milvus_host}:{self._settings.milvus_port}"

    async def aclose(self) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None

    async def create(self, spec: CollectionSpec) -> None:
        await self._post("/v2/vectordb/collections/create", _create_body(spec))
        try:
            await self._post(
                "/v2/vectordb/collections/alter_properties",
                {"collectionName": spec.name, "properties": spec.metadata},
            )
        except MilvusCollectionError:
            await self.drop(spec.name)
            raise

    async def exists(self, name: str) -> bool:
        data = await self._post("/v2/vectordb/collections/has", {"collectionName": name})
        return bool(data.get("has") or data.get("hasCollection"))

    async def describe(self, name: str) -> CollectionDescription:
        data = await self._post("/v2/vectordb/collections/describe", {"collectionName": name})
        return _parse_description(name, data)

    async def drop(self, name: str) -> None:
        await self._post("/v2/vectordb/collections/drop", {"collectionName": name})

    async def upsert(self, name: str, rows: list[dict]) -> None:
        await self._post(
            "/v2/vectordb/entities/upsert",
            {"collectionName": name, "data": rows},
        )

    async def delete_where(self, name: str, filter_expr: str) -> None:
        await self._post(
            "/v2/vectordb/entities/delete",
            {"collectionName": name, "filter": filter_expr},
        )

    async def load(self, name: str) -> None:
        await self._post("/v2/vectordb/collections/load", {"collectionName": name})

    async def search(
        self,
        name: str,
        vector: list[float],
        *,
        filter_expr: str,
        limit: int,
        output_fields: list[str],
    ) -> list[DenseHit]:
        await self.load(name)
        data = await self._request(
            "/v2/vectordb/entities/search",
            {
                "collectionName": name,
                "data": [vector],
                "annsField": "embedding",
                "limit": limit,
                "filter": filter_expr,
                "outputFields": output_fields,
                "searchParams": {"metricType": "COSINE", "params": {"ef": 64}},
            },
        )
        if not isinstance(data, list):
            return []
        hits: list[DenseHit] = []
        for item in data:
            if not isinstance(item, dict):
                continue
            hit = _dense_hit(item)
            if hit is not None:
                hits.append(hit)
        return hits

    async def _request(self, path: str, payload: dict) -> object:
        client = await self._client_obj()
        try:
            response = await client.post(path, json=payload)
        except httpx.HTTPError as exc:
            raise MilvusCollectionError(
                "milvus_unavailable",
                "Milvus is not reachable. The vector index can be rebuilt; Canon stays in SQLite.",
            ) from exc
        try:
            body = response.json()
        except json.JSONDecodeError as exc:
            raise MilvusCollectionError(
                "milvus_rejected",
                f"Milvus returned a non-JSON response ({response.status_code}).",
            ) from exc
        code = body.get("code", 0 if response.is_success else response.status_code)
        if not response.is_success or code not in (0, 200):
            message = str(body.get("message") or body.get("error") or response.text)
            raise MilvusCollectionError("milvus_rejected", message)
        return body.get("data")

    async def _post(self, path: str, payload: dict) -> dict:
        data = await self._request(path, payload)
        return data if isinstance(data, dict) else {}

    async def _client_obj(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(base_url=self.base_url, timeout=30)
        return self._client


def _dense_hit(item: dict) -> DenseHit | None:
    chunk_id = str(item.get("chunk_id") or item.get("id") or "")
    if not chunk_id or "distance" not in item:
        return None
    return DenseHit(
        chunk_id=chunk_id,
        novel_id=str(item.get("novel_id") or ""),
        chapter_id=str(item.get("chapter_id") or ""),
        score=float(item["distance"]),
        text_hash=str(item.get("text_hash") or ""),
        canon_status=str(item.get("canon_status") or ""),
    )


def _create_body(spec: CollectionSpec) -> dict:
    fields = [
        _varchar("id", 64, primary=True),
        _varchar("novel_id", 36),
        _varchar("chapter_id", 36),
        _varchar("chunk_id", 64),
        {"fieldName": "sequence", "dataType": "Int64"},
        _varchar("text_hash", 64),
        {"fieldName": "characters", "dataType": "JSON"},
        {"fieldName": "locations", "dataType": "JSON"},
        _varchar("canon_status", 16),
        _varchar("embedding_model", 128),
        _varchar("embedding_version", 128),
        {
            "fieldName": "embedding",
            "dataType": "FloatVector",
            "elementTypeParams": {"dim": spec.dimension},
        },
        {"fieldName": "created_at", "dataType": "Int64"},
    ]
    names = tuple(field["fieldName"] for field in fields)
    if names != COLLECTION_FIELDS:
        raise MilvusCollectionError("collection_schema_invalid", "Collection fields drifted.")
    return {
        "collectionName": spec.name,
        "schema": {
            "autoId": False,
            "enableDynamicField": False,
            "description": spec.description,
            "fields": fields,
        },
        "indexParams": [
            {
                "fieldName": "embedding",
                "indexName": "embedding",
                "metricType": spec.index.metric_type,
                "params": {
                    "index_type": spec.index.index_type,
                    "M": spec.index.m,
                    "efConstruction": spec.index.ef_construction,
                },
            }
        ],
    }


def _param_map(field: dict) -> dict:
    raw = field.get("elementTypeParams")
    if not isinstance(raw, dict):
        raw = field.get("params")
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, list):
        return {
            str(item.get("key")): item.get("value")
            for item in raw
            if isinstance(item, dict) and item.get("key")
        }
    return {}


def _property_map(properties: object) -> dict[str, str]:
    if isinstance(properties, dict):
        return {str(key): str(value) for key, value in properties.items()}
    if not isinstance(properties, list):
        return {}
    mapped: dict[str, str] = {}
    for item in properties:
        if isinstance(item, dict) and item.get("key"):
            mapped[str(item["key"])] = str(item.get("value"))
    return mapped


def _varchar(name: str, max_length: int, *, primary: bool = False) -> dict:
    field = {
        "fieldName": name,
        "dataType": "VarChar",
        "elementTypeParams": {"max_length": max_length},
    }
    if primary:
        field["isPrimary"] = True
    return field


def _parse_description(name: str, data: dict) -> CollectionDescription:
    fields = data.get("fields") or []
    names: list[str] = []
    dimension = 0
    for field in fields:
        field_name = str(field.get("fieldName") or field.get("name") or "")
        if field_name:
            names.append(field_name)
        if field_name == "embedding":
            dimension = int(_param_map(field).get("dim") or 0)
    description = data.get("description") or ""
    if not description and isinstance(data.get("schema"), dict):
        description = data["schema"].get("description") or ""
    metadata: dict[str, str] = {}
    if isinstance(description, str) and description.startswith("{"):
        loaded = json.loads(description)
        metadata = {str(key): str(value) for key, value in loaded.items()}
    metadata.update(_property_map(data.get("properties")))
    if metadata.get("dimension") and dimension and metadata["dimension"] != str(dimension):
        raise MilvusCollectionError(
            "dimension_mismatch",
            "Collection vector dimension does not match its profile metadata.",
        )
    index_payload = (data.get("indexParams") or data.get("indexes") or [{}])[0]
    params = index_payload.get("params") or {}
    index = IndexParameterProfile(
        index_type=str(params.get("index_type") or metadata.get("index_type") or "HNSW"),
        metric_type=str(index_payload.get("metricType") or metadata.get("metric_type") or "COSINE"),
        m=int(params.get("M") or 16),
        ef_construction=int(params.get("efConstruction") or 200),
    )
    return CollectionDescription(
        name=str(data.get("collectionName") or name),
        dimension=dimension,
        field_names=tuple(names),
        metadata=metadata,
        index=index,
    )
