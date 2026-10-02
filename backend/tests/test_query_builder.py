from app.adapters.sqlite import bootstrap_local_runtime, session_scope
from app.domain.memory import ForeshadowingStatus
from app.schemas.retrieval import QUERY_BUILDER_VERSION, QueryBuilderInput
from app.services import catalog
from app.services.memory_repository import MemoryRepository
from app.services.memory_snapshot import create_memory_snapshot
from app.services.query_builder import MemoryHints, build_retrieval_query, load_memory_hints


def test_same_context_builds_the_same_query_and_metadata_hints() -> None:
    context = QueryBuilderInput(
        novel_id="novel",
        chapter_goal="让林深认出旧伞",
        current_scene="雨巷口",
        characters=["林深", " 林深 ", ""],
        locations=["雨巷"],
        events=["认出旧伞"],
        foreshadowing=["伞的主人"],
        previous_chapter_state="她还在雨里。",
    )
    first = build_retrieval_query(context)
    second = build_retrieval_query(context)
    assert first.model_dump(mode="json") == second.model_dump(mode="json")
    assert first.query_builder_version == QUERY_BUILDER_VERSION
    assert first.include_draft is False
    assert first.characters == ["林深"]
    assert first.metadata_hints.characters == ["林深"]
    assert first.metadata_hints.locations == ["雨巷"]
    assert first.metadata_hints.foreshadowing == ["伞的主人"]
    assert "章节目标：让林深认出旧伞" in first.semantic_query_text
    assert "人物：林深" in first.semantic_query_text
    assert "地点：雨巷" in first.semantic_query_text
    assert "伏笔：伞的主人" in first.semantic_query_text
    assert "上一章：她还在雨里。" in first.semantic_query_text


def test_missing_memory_still_builds_a_semantic_query() -> None:
    query = build_retrieval_query(
        QueryBuilderInput(novel_id="novel", chapter_goal="写下下一场"),
        memory=MemoryHints(),
    )
    assert query.semantic_query_text == "章节目标：写下下一场"
    assert query.characters == []
    assert query.metadata_hints.locations == []
    assert query.previous_chapter_state == ""
    empty = build_retrieval_query(QueryBuilderInput(novel_id="novel"))
    assert empty.semantic_query_text == "续写当前章节"


def test_explicit_entities_win_and_memory_fills_gaps() -> None:
    memory = MemoryHints(
        characters=("林深",),
        events=("旧约",),
        foreshadowing=("伞的主人",),
        previous_chapter_state="第1章",
    )
    planned = build_retrieval_query(
        QueryBuilderInput(novel_id="novel", chapter_goal="换人", characters=["周晚"]),
        memory=memory,
    )
    assert planned.characters == ["周晚"]
    assert planned.events == ["旧约"]
    assert planned.foreshadowing == ["伞的主人"]
    assert planned.previous_chapter_state == "第1章"
    caller_state = build_retrieval_query(
        QueryBuilderInput(
            novel_id="novel",
            chapter_goal="换人",
            previous_chapter_state="她放下伞。",
        ),
        memory=memory,
    )
    assert caller_state.previous_chapter_state == "她放下伞。"


def test_empty_memory_and_saved_memory_both_build(isolated_data_dir) -> None:
    _settings, engine, factory = bootstrap_local_runtime()
    try:
        for session in session_scope(factory):
            novel = catalog.create_novel(session, "雨巷")
            empty = load_memory_hints(session, novel.id)
            assert empty.characters == ()
            query = build_retrieval_query(
                QueryBuilderInput(novel_id=novel.id, chapter_goal="继续走"),
                memory=empty,
            )
            assert query.semantic_query_text == "章节目标：继续走"
            repo = MemoryRepository(session)
            repo.create_character(novel.id, "林深")
            repo.create_foreshadowing(novel.id, "伞的主人", ForeshadowingStatus.PLANTED)
            chapter = catalog.create_chapter(session, novel.id, body="林深走进雨里。")
            create_memory_snapshot(session, novel.id, chapter.id)
            recalled = load_memory_hints(session, novel.id)
            built = build_retrieval_query(
                QueryBuilderInput(novel_id=novel.id, chapter_goal="认出伞"),
                memory=recalled,
            )
            assert built.metadata_hints.characters == ["林深"]
            assert built.metadata_hints.foreshadowing == ["伞的主人"]
            assert built.previous_chapter_state == chapter.display_title
            assert "人物：林深" in built.semantic_query_text
    finally:
        engine.dispose()
