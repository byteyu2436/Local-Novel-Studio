import json
from hashlib import sha256

INDEX_STATUSES = ("building", "validating", "active", "failed", "superseded", "retired")


def index_manifest(
    *,
    collection_name: str,
    embedding_profile_id: str,
    chunking_version: str,
    index_version: str,
    record_count: int,
    corpus_checksum: str = "",
) -> tuple[str, str]:
    payload = {
        "chunking_version": chunking_version,
        "collection_name": collection_name,
        "corpus_checksum": corpus_checksum,
        "embedding_profile_id": embedding_profile_id,
        "index_version": index_version,
        "record_count": record_count,
    }
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return text, sha256(text.encode()).hexdigest()
