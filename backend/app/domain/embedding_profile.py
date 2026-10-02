from dataclasses import dataclass
from hashlib import sha256


@dataclass(frozen=True)
class EmbeddingProfileSpec:
    embedding_model_id: str
    embedding_model_tag: str
    embedding_model_version: str
    dimension: int
    normalization: str
    chunking_version: str

    def __post_init__(self) -> None:
        if self.dimension < 1:
            raise ValueError("dimension must be positive")
        if self.normalization not in {"none", "l2"}:
            raise ValueError("normalization must be none or l2")
        if not self.chunking_version.strip():
            raise ValueError("chunking_version is required")


def profile_fingerprint(spec: EmbeddingProfileSpec) -> str:
    raw = "\n".join(
        [
            spec.embedding_model_id,
            spec.embedding_model_tag,
            spec.embedding_model_version,
            str(spec.dimension),
            spec.normalization,
            spec.chunking_version,
        ]
    )
    return sha256(raw.encode()).hexdigest()


def index_version_for(fingerprint: str) -> str:
    return sha256(f"index\n{fingerprint}".encode()).hexdigest()[:32]
