from alembic import context
from app.adapters.sqlite.base import Base
from app.adapters.sqlite.chunks import CanonChunk
from app.adapters.sqlite.continuation import (
    AcceptOperation,
    ChapterPlanVersion,
    ConsistencyIssueRecord,
    DraftVersion,
)
from app.adapters.sqlite.embeddings import ChunkEmbedding, EmbeddingProfileRecord
from app.adapters.sqlite.index_registry import IndexVersionRecord
from app.adapters.sqlite.initialization import NovelInitializationRun
from app.adapters.sqlite.memory import (
    EntityResolutionRecord,
    MemoryCharacter,
    MemoryConflict,
    MemoryEvent,
    MemoryFact,
    MemoryForeshadowing,
    MemoryNamedEntity,
    MemoryOperationLog,
    MemoryReduceApplication,
    MemoryRelationship,
    MemorySnapshot,
    MemoryStyleProfile,
    MemoryTimeline,
    MemoryWorldFact,
    NovelMemoryRevision,
)
from app.adapters.sqlite.models import (
    AppSetting,
    ChapterAnalysis,
    ImportSource,
    ImportSourceNormalizedText,
)
from sqlalchemy import engine_from_config, pool

config = context.config
target_metadata = Base.metadata

# Imported so Alembic autogenerate can see the current models.
_ = (
    AppSetting,
    CanonChunk,
    ChunkEmbedding,
    ChapterAnalysis,
    EmbeddingProfileRecord,
    IndexVersionRecord,
    NovelInitializationRun,
    AcceptOperation,
    ChapterPlanVersion,
    ConsistencyIssueRecord,
    DraftVersion,
    ImportSource,
    ImportSourceNormalizedText,
    MemoryCharacter,
    MemoryEvent,
    MemoryFact,
    MemoryForeshadowing,
    MemoryRelationship,
    MemoryStyleProfile,
    MemoryTimeline,
    EntityResolutionRecord,
    MemoryConflict,
    MemoryNamedEntity,
    MemoryOperationLog,
    MemoryReduceApplication,
    MemoryRelationship,
    MemorySnapshot,
    MemoryWorldFact,
    NovelMemoryRevision,
)


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
        future=True,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
