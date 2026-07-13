"""Tests for the structured, side-effect-free AI tool service layer."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from suwayomi.ai_service import (
    AiInteractionState,
    get_chapters_for_agent,
    is_successful_conversation_reset,
    search_manga_for_agent,
    select_search_sources,
)
from suwayomi.models import Chapter, Manga, SearchResult, Source


def _source(source_id: str, name: str, lang: str = "zh") -> Source:
    return Source(id=source_id, name=name, lang=lang, display_name=name)


def _manga(manga_id: int, title: str, source_id: int = 1) -> Manga:
    return Manga(
        id=manga_id,
        source_id=source_id,
        url="",
        title=title,
        author="ONE",
        description="兴趣使然成为英雄的琦玉",
        genre=["动作", "喜剧"],
    )


def _chapter(chapter_id: int, number: float, source_order: int) -> Chapter:
    return Chapter(
        id=chapter_id,
        url="",
        name=f"第{number:g}话",
        chapter_number=number,
        source_order=source_order,
        manga_id=10,
    )


def test_select_search_sources_skips_local_and_matches_hint():
    sources = [_source("0", "Local"), _source("1", "拷贝漫画"), _source("2", "MangaDex", "en")]
    selected = select_search_sources(sources, "拷贝", 0, 5)
    assert [source.id for source in selected] == ["1"]


def test_select_search_sources_honors_default_source():
    sources = [_source("1", "A"), _source("2", "B")]
    selected = select_search_sources(sources, "", 2, 5)
    assert [source.id for source in selected] == ["2"]


def test_ai_interaction_state_isolates_group_senders_and_expires():
    state = AiInteractionState(ttl=600)
    sender_a = ("qq:group:123", "user-a")
    sender_b = ("qq:group:123", "user-b")
    state.remember_chapters(sender_a, 10, {100}, now=1000)

    assert state.was_chapter_exposed(sender_a, 10, 100, now=1001) is True
    assert state.was_chapter_exposed(sender_b, 10, 100, now=1001) is False
    assert state.was_chapter_exposed(sender_a, 10, 100, now=1601) is False


def test_ai_interaction_state_deduplicates_only_same_turn_receipt():
    state = AiInteractionState(ttl=600)
    scope = ("qq:group:123", "user-a")
    receipt = (scope, 12345, 10, 100)
    other_turn = (scope, 67890, 10, 100)

    assert state.already_sent(receipt, now=1000) is False
    state.mark_sent(receipt, now=1000)
    assert state.already_sent(receipt, now=1001) is True
    assert state.already_sent(other_turn, now=1001) is False


def test_ai_interaction_state_clear_origin_is_scoped():
    state = AiInteractionState(ttl=600)
    sender_a = ("qq:group:123", "user-a")
    sender_b = ("qq:group:123", "user-b")
    other_group = ("qq:group:456", "user-a")
    for scope in (sender_a, sender_b, other_group):
        state.remember_chapters(scope, 10, {100}, now=1000)
        state.mark_sent((scope, 12345, 10, 100), now=1000)

    state.clear_origin("qq:group:123")

    assert state.was_chapter_exposed(sender_a, 10, 100, now=1001) is False
    assert state.was_chapter_exposed(sender_b, 10, 100, now=1001) is False
    assert state.was_chapter_exposed(other_group, 10, 100, now=1001) is True
    assert state.already_sent((sender_a, 12345, 10, 100), now=1001) is False
    assert state.already_sent((other_group, 12345, 10, 100), now=1001) is True


def test_successful_conversation_reset_detection():
    marked_event = SimpleNamespace(
        get_extra=lambda key, default=False: key == "_clean_group_context_session",
        get_result=lambda: None,
    )
    third_party_event = SimpleNamespace(
        get_extra=lambda _key, default=False: default,
        get_result=lambda: SimpleNamespace(
            chain=[SimpleNamespace(text="✅ Conversation reset successfully.")]
        ),
    )
    failed_event = SimpleNamespace(
        get_extra=lambda _key, default=False: default,
        get_result=lambda: SimpleNamespace(
            chain=[SimpleNamespace(text="Reset command requires admin permission")]
        ),
    )

    assert is_successful_conversation_reset(marked_event) is True
    assert is_successful_conversation_reset(third_party_event) is True
    assert is_successful_conversation_reset(failed_event) is False


@pytest.mark.asyncio
async def test_agent_search_returns_stable_ids_and_survives_one_source_error():
    client = SimpleNamespace()
    client.get_sources = AsyncMock(return_value=[_source("1", "A"), _source("2", "B")])

    async def search(source_id, query):
        if str(source_id) == "1":
            return SearchResult(mangas=[_manga(10, "一拳超人")])
        raise RuntimeError("source unavailable")

    client.search_manga = search
    result = await search_manga_for_agent(
        client,
        {"ai_max_sources": 5, "ai_results_per_source": 5},
        "一拳超人",
    )

    assert result["success"] is True
    assert result["results"][0]["manga_id"] == 10
    assert result["results"][0]["description"]
    assert len(result["source_errors"]) == 1


@pytest.mark.asyncio
async def test_agent_chapters_selects_latest_by_source_order():
    manga = _manga(10, "一拳超人")
    chapters = [_chapter(100, 1, 2), _chapter(200, 2, 1)]
    client = SimpleNamespace(
        get_manga=AsyncMock(return_value=manga),
        get_chapters=AsyncMock(return_value=chapters),
    )
    get_kv = AsyncMock(return_value={})
    put_kv = AsyncMock()

    result = await get_chapters_for_agent(
        client, get_kv, put_kv, {"chapter_cache_hours": 0}, 10, "latest"
    )

    assert result["success"] is True
    assert result["selected_chapter"]["chapter_id"] == 200
    assert result["manga"]["manga_id"] == 10


@pytest.mark.asyncio
async def test_agent_chapters_returns_ids_for_duplicate_numbers():
    manga = _manga(10, "测试漫画")
    chapters = [_chapter(100, 7, 1), _chapter(200, 7, 2)]
    client = SimpleNamespace(
        get_manga=AsyncMock(return_value=manga),
        get_chapters=AsyncMock(return_value=chapters),
    )

    result = await get_chapters_for_agent(
        client,
        AsyncMock(return_value={}),
        AsyncMock(),
        {"chapter_cache_hours": 0},
        10,
        "7",
    )

    assert result["success"] is False
    assert result["selected_chapter"] is None
    assert {chapter["chapter_id"] for chapter in result["chapters"]} == {100, 200}
    assert "明确选择" in result["error"]


@pytest.mark.asyncio
async def test_agent_chapters_supports_explicit_chapter_id():
    manga = _manga(10, "测试漫画")
    chapters = [_chapter(100, 7, 1), _chapter(200, 7, 2)]
    client = SimpleNamespace(
        get_manga=AsyncMock(return_value=manga),
        get_chapters=AsyncMock(return_value=chapters),
    )

    result = await get_chapters_for_agent(
        client,
        AsyncMock(return_value={}),
        AsyncMock(),
        {"chapter_cache_hours": 0},
        10,
        "ID:200",
    )

    assert result["success"] is True
    assert result["selected_chapter"]["chapter_id"] == 200
