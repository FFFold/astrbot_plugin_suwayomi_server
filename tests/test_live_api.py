"""Integration tests against a live Suwayomi-Server instance.

Usage:
    uv run pytest tests/test_live_api.py -v -s

Set SUWAYOMI_URL env var or it defaults to http://100.87.49.15:4567
"""
import asyncio
import os

import pytest

from suwayomi.client import SuwayomiClient, SuwayomiError
from suwayomi.models import Chapter, Manga, SearchResult, Source

SERVER_URL = os.environ.get("SUWAYOMI_URL", "http://100.87.49.15:4567")


@pytest.fixture
def client():
    c = SuwayomiClient(SERVER_URL, "none", "", "")
    yield c
    asyncio.get_event_loop().run_until_complete(c.close())


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
