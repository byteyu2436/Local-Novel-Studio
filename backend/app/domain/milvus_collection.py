import json
import re
from dataclasses import dataclass

_NAME_CHARS = re.compile(r"[^0-9A-Za-z_]+")
_COLLECTION_NAME = re.compile(r"^[A-Za-z_][0-9A-Za-z_]*$")

COLLECTION_FIELDS = (
    "id",
    "novel_id",
    "chapter_id",
    "chunk_id",
    "sequence",
    "text_hash",
    "characters",
    "locations",
    "canon_status",
    "embedding_model",
    "embedding_version",
    "embedding",
    "created_at",
)


class MilvusCollectionError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class IndexParameterProfile:
    """P0 index. Normalized vectors use cosine distance on an HNSW graph."""

    index_type: str = "HNSW"
    metric_type: str = "COSINE"
    m: int = 16
    ef_construction: int = 200

    def __post_init__(self) -> None:
        if self.m < 2 or self.ef_construction < 1:
            raise ValueError("HNSW parameters must be positive.")


@dataclass(frozen=True)
class CollectionSpec:
    name: str
    dimension: int
    index: IndexParameterProfile
    metadata: dict[str, str]
    description: str


def collection_name(
    *, model_id: str, model_tag: str, index_version: str, name_suffix: str | None = None
) -> str:
    name = f"novel_chunks_{_token(model_id)}_{_token(model_tag)}_{_token(index_version)}"
    if name_suffix:
        name = f"{name}_{_token(name_suffix)}"
    if len(name) > 255 or _COLLECTION_NAME.fullmatch(name) is None:
        raise MilvusCollectionError(
            "collection_name_invalid",
            "Collection name is empty, too long, or contains unsupported characters.",
        )
    return name


def build_collection_spec(
    *,
    profile_id: str,
    embedding_model_id: str,
    embedding_model_tag: str,
    embedding_model_version: str,
    dimension: int,
    chunking_version: str,
    index_version: str,
    requested_dimension: int | None = None,
    index: IndexParameterProfile | None = None,
    name_suffix: str | None = None,
) -> CollectionSpec:
    if dimension < 1:
        raise MilvusCollectionError("dimension_mismatch", "Embedding dimension must be positive.")
    if requested_dimension is not None and requested_dimension != dimension:
        raise MilvusCollectionError(
            "dimension_mismatch",
            "Requested dimension "
            f"{requested_dimension} does not match profile dimension {dimension}.",
        )
    resolved = index or IndexParameterProfile()
    metadata = {
        "profile_id": profile_id,
        "index_version": index_version,
        "chunking_version": chunking_version,
        "embedding_model": f"{embedding_model_id}:{embedding_model_tag}",
        "embedding_version": embedding_model_version,
        "dimension": str(dimension),
        "metric_type": resolved.metric_type,
        "index_type": resolved.index_type,
    }
    return CollectionSpec(
        name=collection_name(
            model_id=embedding_model_id,
            model_tag=embedding_model_tag,
            index_version=index_version,
            name_suffix=name_suffix,
        ),
        dimension=dimension,
        index=resolved,
        metadata=metadata,
        description=json.dumps(metadata, ensure_ascii=False, sort_keys=True),
    )


def _token(value: str) -> str:
    cleaned = _NAME_CHARS.sub("_", value.strip()).strip("_")
    if not cleaned:
        raise MilvusCollectionError(
            "collection_name_invalid",
            "Collection name parts cannot be empty.",
        )
    return cleaned
