import json
import math
import re

import httpx
from app.adapters.milvus.collections import MilvusCollectionClient
from app.settings import get_settings


def mock_milvus() -> tuple[MilvusCollectionClient, dict[str, dict[str, dict]], httpx.AsyncClient]:
    saved: dict[str, dict] = {}
    entities: dict[str, dict[str, dict]] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode("utf-8") or "{}")
        name = body.get("collectionName", "")
        path = request.url.path
        if path.endswith("/create"):
            saved[name] = body
            entities[name] = {}
            return httpx.Response(200, json={"code": 0, "data": {}})
        if path.endswith("/alter_properties"):
            saved[name]["properties"] = body.get("properties") or {}
            return httpx.Response(200, json={"code": 0, "data": {}})
        if path.endswith("/has"):
            return httpx.Response(200, json={"code": 0, "data": {"has": name in saved}})
        if path.endswith("/describe"):
            if name not in saved:
                return httpx.Response(404, json={"code": 404, "message": "missing"})
            schema = saved[name]["schema"]
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "data": {
                        "collectionName": name,
                        "description": schema["description"],
                        "fields": schema["fields"],
                        "indexParams": saved[name]["indexParams"],
                        "properties": [
                            {"key": key, "value": value}
                            for key, value in (saved[name].get("properties") or {}).items()
                        ],
                    },
                },
            )
        if path.endswith("/upsert"):
            bucket = entities.setdefault(name, {})
            for row in body["data"]:
                assert "text" not in row
                bucket[row["id"]] = row
            return httpx.Response(200, json={"code": 0, "data": {}})
        if path.endswith("/load"):
            return httpx.Response(200, json={"code": 0, "data": {}})
        if path.endswith("/search"):
            rows = [
                row
                for row in entities.get(name, {}).values()
                if _matches(row, body.get("filter", ""))
            ]
            query = (body.get("data") or [[]])[0]
            ranked = sorted(
                rows,
                key=lambda row: _cosine(query, row.get("embedding") or []),
                reverse=True,
            )
            limit = int(body.get("limit") or len(ranked))
            data = []
            for row in ranked[:limit]:
                hit = dict(row)
                hit.pop("embedding", None)
                hit["distance"] = _cosine(query, row.get("embedding") or [])
                data.append(hit)
            return httpx.Response(200, json={"code": 0, "data": data})
        if path.endswith("/drop"):
            saved.pop(name, None)
            entities.pop(name, None)
            return httpx.Response(200, json={"code": 0, "data": {}})
        return httpx.Response(404, json={"code": 404, "message": "missing"})

    http_client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="http://127.0.0.1:19530",
    )
    return MilvusCollectionClient(get_settings(), client=http_client), entities, http_client


def _matches(row: dict, expr: str) -> bool:
    for field, value in re.findall(r'(\w+) == "([^"]*)"', expr):
        if str(row.get(field, "")) != value:
            return False
    for field, value in re.findall(r'json_contains\((\w+), "([^"]*)"\)', expr):
        if value not in (row.get(field) or []):
            return False
    return True


def _cosine(left: list[float], right: list[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 1.0
    return sum(a * b for a, b in zip(left, right, strict=True)) / (
        math.sqrt(sum(a * a for a in left)) * math.sqrt(sum(b * b for b in right)) or 1
    )
