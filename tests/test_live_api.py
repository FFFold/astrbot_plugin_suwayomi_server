"""Integration tests against a live Suwayomi-Server instance.

Usage:
    uv run pytest tests/test_live_api.py -v -s

Set SUWAYOMI_URL env var or it defaults to http://100.87.49.15:4567
"""
import os

import pytest
import pytest_asyncio

from suwayomi.client import SuwayomiClient, SuwayomiError
from suwayomi.models import Chapter, Manga, SearchResult, Source
from suwayomi.ai_service import (
    get_chapters_for_agent,
    search_manga_for_agent,
    select_search_sources,
)

SERVER_URL = os.environ.get("SUWAYOMI_URL", "http://100.87.49.15:4567")


@pytest_asyncio.fixture
async def client():
    c = SuwayomiClient(SERVER_URL, "none", "", "")
    yield c
    await c.close()


# ── Sources ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_sources(client):
    sources = await client.get_sources()
    assert len(sources) > 0, "Should have at least one source"
    for src in sources:
        assert isinstance(src, Source)
        assert src.id
        assert src.name, f"Source {src.id} should have a name"
    print(f"\n  Found {len(sources)} sources:")
    for s in sources:
        print(f"    [{s.id}] {s.display_name} ({s.lang})")


# ── Search ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_search_manga(client):
    sources = await client.get_sources()
    zh_sources = [s for s in sources if s.lang == "zh" and s.id != "0"]
    assert zh_sources, "Need at least one Chinese source"

    src = zh_sources[0]
    result = await client.search_manga(src.id, "海贼王")
    assert isinstance(result, SearchResult)
    print(f"\n  Search '海贼王' on {src.display_name}: {len(result.mangas)} results")
    if result.mangas:
        m = result.mangas[0]
        assert m.id > 0
        assert m.title
        print(f"    First: [{m.id}] {m.title} ({m.status})")


@pytest.mark.asyncio
async def test_search_manga_all_zh_sources(client):
    sources = await client.get_sources()
    zh_sources = [s for s in sources if s.lang == "zh" and s.id != "0"]

    total = 0
    for src in zh_sources:
        try:
            result = await client.search_manga(src.id, "one piece")
            total += len(result.mangas)
            print(f"\n  {src.display_name}: {len(result.mangas)} results")
        except SuwayomiError as e:
            print(f"\n  {src.display_name}: ERROR - {e}")

    assert total > 0, "Should find results across sources"


# ── Manga by ID ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_manga(client):
    # First search to get a valid manga ID
    sources = await client.get_sources()
    zh_sources = [s for s in sources if s.lang == "zh" and s.id != "0"]
    result = await client.search_manga(zh_sources[0].id, "海贼王")
    assert result.mangas, "Search should return results"

    manga_id = result.mangas[0].id
    manga = await client.get_manga(manga_id)
    assert isinstance(manga, Manga)
    assert manga.id == manga_id
    assert manga.title
    print(f"\n  manga({manga_id}): {manga.title} | status={manga.status} | in_library={manga.in_library}")


# ── Search by title (library-level) ─────────────────────────────

@pytest.mark.asyncio
async def test_search_manga_by_title(client):
    mangas = await client.search_manga_by_title("海贼王")
    assert isinstance(mangas, list)
    print(f"\n  search_manga_by_title('海贼王'): {len(mangas)} results")
    for m in mangas[:3]:
        assert isinstance(m, Manga)
        print(f"    [{m.id}] {m.title}")


# ── Chapters ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_chapters(client):
    # Get a manga that has chapters
    sources = await client.get_sources()
    zh_sources = [s for s in sources if s.lang == "zh" and s.id != "0"]
    result = await client.search_manga(zh_sources[0].id, "海贼王")
    assert result.mangas

    # Try each manga until we find one with chapters
    found = False
    for m in result.mangas[:5]:
        chapters = await client.get_chapters(m.id)
        if chapters:
            assert isinstance(chapters[0], Chapter)
            assert chapters[0].id > 0
            assert chapters[0].name or chapters[0].chapter_number >= 0
            print(f"\n  chapters(manga={m.id}, '{m.title}'): {len(chapters)} chapters")
            print(f"    First: #{chapters[0].chapter_number} '{chapters[0].name}' (id={chapters[0].id})")
            found = True
            break

    if not found:
        print("\n  WARN: no manga with chapters found in top 5 results")


# ── Fetch chapter pages ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_fetch_chapter_pages(client):
    sources = await client.get_sources()
    zh_sources = [s for s in sources if s.lang == "zh" and s.id != "0"]
    result = await client.search_manga(zh_sources[0].id, "海贼王")
    assert result.mangas

    # Find a manga with chapters, then get pages
    for m in result.mangas[:5]:
        chapters = await client.get_chapters(m.id)
        if chapters:
            pages = await client.fetch_chapter_pages(chapters[0].id)
            assert isinstance(pages, list)
            print(f"\n  fetch_chapter_pages(chapter={chapters[0].id}): {len(pages)} pages")
            if pages:
                assert isinstance(pages[0], str)
                print(f"    First page path: {pages[0]}")
                full_url = client.build_image_url(pages[0])
                print(f"    Full URL: {full_url}")
            break


# ── Fetch chapters from source ─────────────────────────────────

@pytest.mark.asyncio
async def test_fetch_chapters(client):
    """Test fetch_chapters mutation - fetches chapter list from manga source.
    This is used when a manga has no chapters in DB (e.g. never opened in WebUI)."""
    sources = await client.get_sources()
    zh_sources = [s for s in sources if s.lang == "zh" and s.id != "0"]
    result = await client.search_manga(zh_sources[0].id, "海贼王")
    assert result.mangas

    manga = result.mangas[0]
    # Fetch chapters from source
    fetched = await client.fetch_chapters(manga.id)
    assert isinstance(fetched, list)
    assert len(fetched) > 0, f"fetch_chapters should return chapters for '{manga.title}'"
    assert isinstance(fetched[0], Chapter)
    assert fetched[0].id > 0
    print(f"\n  fetch_chapters(manga={manga.id}, '{manga.title}'): {len(fetched)} chapters fetched")
    print(f"    First: #{fetched[0].chapter_number} '{fetched[0].name}' (id={fetched[0].id})")
    # After fetch, DB should also have chapters
    db_chapters = await client.get_chapters(manga.id)
    assert len(db_chapters) >= len(fetched), "DB chapters should be >= fetched chapters"


@pytest.mark.asyncio
async def test_fetch_chapters_then_get(client):
    """Test the pattern used in _check_updates: get_chapters returns empty -> fetch_chapters -> get_chapters returns data."""
    sources = await client.get_sources()
    zh_sources = [s for s in sources if s.lang == "zh" and s.id != "0"]

    # Search for a manga that's likely not in the library
    result = await client.search_manga(zh_sources[0].id, "间谍过家家")
    assert result.mangas, "Search should return results"

    manga = result.mangas[0]
    # Fetch chapters from source
    fetched = await client.fetch_chapters(manga.id)
    assert isinstance(fetched, list)
    # Verify DB is populated after fetch
    db_chapters = await client.get_chapters(manga.id)
    assert len(db_chapters) > 0, "get_chapters should return data after fetch_chapters"
    print(f"\n  fetch_chapters_then_get(manga={manga.id}): {len(fetched)} fetched, {len(db_chapters)} in DB")


# ── Library operations ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_library_mangas(client):
    mangas = await client.get_library_mangas()
    assert isinstance(mangas, list)
    print(f"\n  get_library_mangas(): {len(mangas)} manga in library")
    for m in mangas[:3]:
        print(f"    [{m.id}] {m.title}")


# ── Enqueue download ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_enqueue_download(client):
    # This just verifies the API call doesn't error with an empty list
    # We don't actually download anything to avoid side effects
    pass


# ── Error handling ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_nonexistent_manga(client):
    with pytest.raises(SuwayomiError):
        await client.get_manga(999999999)


@pytest.mark.asyncio
async def test_search_invalid_source(client):
    # Should not crash, may return empty or error
    try:
        result = await client.search_manga(0, "test")
        # Local source may return empty
        assert isinstance(result, SearchResult)
    except SuwayomiError:
        pass  # acceptable


# ── AI service ─────────────────────────────────────────────────


class _FakeKV:
    """In-memory KV store for ai_service integration tests."""

    def __init__(self):
        self._store: dict = {}

    async def get(self, key, default=None):
        return self._store.get(key, default)

    async def put(self, key, value):
        self._store[key] = value


@pytest.mark.asyncio
async def test_select_search_sources_skips_local(client):
    """select_search_sources with real sources excludes local source."""
    sources = await client.get_sources()
    selected = select_search_sources(sources, "", 0, 5)
    for s in selected:
        assert s.id != "0", "Local source should be excluded"


@pytest.mark.asyncio
async def test_select_search_sources_matches_hint(client):
    """select_search_sources matches by name, display_name, or lang."""
    sources = await client.get_sources()
    zh = select_search_sources(sources, "zh", 0, 5)
    assert len(zh) > 0, "Should match sources by lang code"


@pytest.mark.asyncio
async def test_select_search_sources_deduplicates_variants(client):
    """select_search_sources puts variants after all unique extensions."""
    sources = await client.get_sources()
    selected = select_search_sources(sources, "", 0, 10)
    assert len(selected) > 0
    # Verify order: all first-of-name entries precede their variants
    seen_first: dict[str, int] = {}
    for i, s in enumerate(selected):
        key = s.name.strip().casefold() or s.display_name.strip().casefold()
        if key not in seen_first:
            seen_first[key] = i
    for s in selected:
        key = s.name.strip().casefold() or s.display_name.strip().casefold()
        # If this isn't the first occurrence, its index must be
        # after the first occurrence of ALL names (i.e. all primaries)
        if seen_first[key] != selected.index(s):
            assert selected.index(s) >= len(seen_first), \
                f"Variant {s.display_name} at index {selected.index(s)} should be after all primaries ({len(seen_first)} unique names)"
    print(f"\n  {len(selected)} sources, {len(seen_first)} unique extensions")


@pytest.mark.asyncio
async def test_ai_search_manga_returns_stable_ids(client):
    """search_manga_for_agent returns stable manga_id and metadata."""
    kv = _FakeKV()
    config = {"ai_max_sources": 3, "ai_results_per_source": 5}
    result = await search_manga_for_agent(client, config, "海贼", source_hint="zh")
    # Must succeed
    assert result["success"] is True
    assert result["result_count"] > 0
    # Each result must have stable manga_id
    for manga in result["results"]:
        assert "manga_id" in manga
        assert isinstance(manga["manga_id"], int)
        assert manga["manga_id"] > 0
        assert "title" in manga
        assert manga["title"]
    # Sources metadata present
    assert result["searched_source_count"] > 0
    assert result["available_source_count"] > 0
    assert len(result["available_sources"]) > 0
    print(f"\n  ai_search: {result['result_count']} results across {result['searched_source_count']} sources")


@pytest.mark.asyncio
async def test_ai_search_manga_empty_query(client):
    """search_manga_for_agent handles empty query gracefully."""
    result = await search_manga_for_agent(client, {}, "", source_hint="zh")
    assert result["success"] is False
    assert "不能为空" in result["error"]


@pytest.mark.asyncio
async def test_ai_get_chapters_latest(client):
    """get_chapters_for_agent 'latest' returns the newest chapter by source_order."""
    kv = _FakeKV()
    config = {"chapter_cache_hours": 0}
    # First search to find a manga with chapters
    search = await search_manga_for_agent(client, {"ai_max_sources": 1, "ai_results_per_source": 5}, "海贼", source_hint="zh")
    assert search["success"] is True
    manga_id = search["results"][0]["manga_id"]

    result = await get_chapters_for_agent(
        client, kv.get, kv.put, config, manga_id, selector="latest", refresh=True
    )
    assert result["success"] is True
    assert result["selected_chapter"] is not None
    sel = result["selected_chapter"]
    assert "chapter_id" in sel
    assert isinstance(sel["chapter_id"], int)
    assert sel["chapter_id"] > 0
    # Latest should return exactly 1 chapter
    assert len(result["chapters"]) == 1
    print(f"\n  latest: ch #{sel['chapter_number']} (id={sel['chapter_id']}) so={sel['source_order']}")


@pytest.mark.asyncio
async def test_ai_get_chapters_list(client):
    """get_chapters_for_agent 'list' returns newest chapters first."""
    kv = _FakeKV()
    config = {"chapter_cache_hours": 0}
    search = await search_manga_for_agent(client, {"ai_max_sources": 1, "ai_results_per_source": 5}, "海贼", source_hint="zh")
    assert search["success"] is True
    manga_id = search["results"][0]["manga_id"]

    result = await get_chapters_for_agent(
        client, kv.get, kv.put, config, manga_id, selector="list", limit=10, refresh=True
    )
    assert result["success"] is True
    assert len(result["chapters"]) > 1, "list should return multiple chapters"
    # Newest chapters should come first (highest source_order = first in list)
    chapters = result["chapters"]
    for i in range(len(chapters) - 1):
        assert chapters[i]["source_order"] >= chapters[i + 1]["source_order"], \
            f"章节 {i} (so={chapters[i]['source_order']}) 应新于或等于章节 {i+1} (so={chapters[i+1]['source_order']})"
    assert result["selected_chapter"] is None
    print(f"\n  list: {len(chapters)} chapters, newest so={chapters[0]['source_order']}")


@pytest.mark.asyncio
async def test_ai_get_chapters_by_number(client):
    """get_chapters_for_agent selects a specific chapter by number."""
    kv = _FakeKV()
    config = {"chapter_cache_hours": 0}
    search = await search_manga_for_agent(client, {"ai_max_sources": 1, "ai_results_per_source": 5}, "海贼", source_hint="zh")
    assert search["success"] is True
    manga_id = search["results"][0]["manga_id"]

    # First get the list to find a valid chapter number
    list_result = await get_chapters_for_agent(
        client, kv.get, kv.put, config, manga_id, selector="list", limit=20, refresh=True
    )
    assert len(list_result["chapters"]) > 0
    target_ch = list_result["chapters"][0]
    number = target_ch["chapter_number"]

    result = await get_chapters_for_agent(
        client, kv.get, kv.put, config, manga_id, selector=str(number), refresh=True
    )
    assert result["success"] is True
    assert result["selected_chapter"] is not None
    assert result["selected_chapter"]["chapter_id"] == target_ch["chapter_id"]
    assert result["selected_chapter"]["chapter_number"] == number
    print(f"\n  by_number: ch #{number} (id={target_ch['chapter_id']})")


@pytest.mark.asyncio
async def test_ai_get_chapters_by_id(client):
    """get_chapters_for_agent selects a specific chapter by ID:xxx syntax."""
    kv = _FakeKV()
    config = {"chapter_cache_hours": 0}
    search = await search_manga_for_agent(client, {"ai_max_sources": 1, "ai_results_per_source": 5}, "海贼", source_hint="zh")
    assert search["success"] is True
    manga_id = search["results"][0]["manga_id"]

    list_result = await get_chapters_for_agent(
        client, kv.get, kv.put, config, manga_id, selector="list", limit=20, refresh=True
    )
    assert len(list_result["chapters"]) > 0
    target_ch = list_result["chapters"][0]

    result = await get_chapters_for_agent(
        client, kv.get, kv.put, config, manga_id, selector=f"id:{target_ch['chapter_id']}", refresh=True
    )
    assert result["success"] is True
    assert result["selected_chapter"] is not None
    assert result["selected_chapter"]["chapter_id"] == target_ch["chapter_id"]
    print(f"\n  by_id: ch #{target_ch['chapter_number']} (id={target_ch['chapter_id']})")


@pytest.mark.asyncio
async def test_ai_get_chapters_nonexistent(client):
    """get_chapters_for_agent raises on nonexistent manga."""
    kv = _FakeKV()
    config = {"chapter_cache_hours": 0}
    with pytest.raises(SuwayomiError):
        await get_chapters_for_agent(client, kv.get, kv.put, config, 999999999, selector="latest")
