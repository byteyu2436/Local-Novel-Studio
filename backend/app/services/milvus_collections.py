from app.adapters.milvus.collections import CollectionDescription, MilvusCollectionClient
from app.adapters.sqlite.embeddings import EmbeddingProfileRecord
from app.domain.milvus_collection import (
    COLLECTION_FIELDS,
    CollectionSpec,
    MilvusCollectionError,
    build_collection_spec,
)


async def ensure_profile_collection(
    client: MilvusCollectionClient,
    profile: EmbeddingProfileRecord,
    *,
    requested_dimension: int | None = None,
) -> CollectionDescription:
    spec = spec_for_profile(profile, requested_dimension=requested_dimension)
    if await client.exists(spec.name):
        current = await client.describe(spec.name)
        _require_same_space(spec, current)
        return current
    await client.create(spec)
    created = await client.describe(spec.name)
    _require_same_space(spec, created)
    return created


async def drop_profile_collection(client: MilvusCollectionClient, name: str) -> None:
    """Drop only the rebuildable index. Callers must not delete SQLite rows here."""

    if await client.exists(name):
        await client.drop(name)


def spec_for_profile(
    profile: EmbeddingProfileRecord, *, requested_dimension: int | None = None
) -> CollectionSpec:
    return build_collection_spec(
        profile_id=profile.id,
        embedding_model_id=profile.embedding_model_id,
        embedding_model_tag=profile.embedding_model_tag,
        embedding_model_version=profile.embedding_model_version,
        dimension=profile.dimension,
        chunking_version=profile.chunking_version,
        index_version=profile.index_version,
        requested_dimension=requested_dimension,
    )


def _require_same_space(spec: CollectionSpec, current: CollectionDescription) -> None:
    if current.dimension != spec.dimension:
        raise MilvusCollectionError(
            "dimension_mismatch",
            f"Collection {current.name} has dimension {current.dimension}, "
            f"expected {spec.dimension}.",
        )
    if current.metadata.get("profile_id") != spec.metadata["profile_id"]:
        raise MilvusCollectionError(
            "collection_profile_mismatch",
            "Collection metadata does not identify this index profile.",
        )
    if current.field_names != COLLECTION_FIELDS:
        raise MilvusCollectionError(
            "collection_schema_mismatch",
            "Collection fields do not match the Canon chunk index schema.",
        )
