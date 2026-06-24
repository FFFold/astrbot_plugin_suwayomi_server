from suwayomi.models import Source, Manga, Chapter, SearchResult


def test_source_from_dict():
    data = {"id": 123, "name": "mangadex", "lang": "en", "displayName": "MangaDex", "supportsLatest": True}
    src = Source.from_dict(data)
    assert src.id == 123
    assert src.name == "mangadex"
    assert src.display_name == "MangaDex"
    assert src.lang == "en"
    assert src.supports_latest is True


def test_manga_from_dict():
    data = {
        "id": 42,
        "sourceId": 123,
        "url": "/manga/42",
        "title": "One Piece",
        "status": "ONGOING",
        "thumbnailUrl": "https://example.com/thumb.jpg",
        "inLibrary": True,
        "author": "Oda",
        "artist": "Oda",
        "description": "Pirate manga",
        "genre": ["Action", "Adventure"],
    }
    manga = Manga.from_dict(data)
    assert manga.id == 42
    assert manga.title == "One Piece"
    assert manga.status == "ONGOING"
    assert manga.in_library is True
    assert manga.author == "Oda"
    assert manga.genre == ["Action", "Adventure"]


def test_chapter_from_dict():
    data = {
        "id": 101,
        "url": "/chapter/101",
        "name": "Chapter 1",
        "chapterNumber": 1.0,
        "uploadDate": 1700000000,
        "isRead": False,
        "isDownloaded": True,
        "isBookmarked": False,
        "lastPageRead": 0,
        "sourceOrder": 1,
        "mangaId": 42,
    }
    ch = Chapter.from_dict(data)
    assert ch.id == 101
    assert ch.name == "Chapter 1"
    assert ch.chapter_number == 1.0
    assert ch.is_read is False
    assert ch.is_downloaded is True


def test_search_result_from_dict():
    data = {
        "mangas": [
            {"id": 1, "title": "A", "url": "/a", "sourceId": 10, "status": "ONGOING"},
            {"id": 2, "title": "B", "url": "/b", "sourceId": 10, "status": "COMPLETED"},
        ],
        "hasNextPage": True,
    }
    sr = SearchResult.from_dict(data)
    assert len(sr.mangas) == 2
    assert sr.has_next_page is True
    assert sr.mangas[0].title == "A"
