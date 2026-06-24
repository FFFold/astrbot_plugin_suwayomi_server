from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Source:
    id: int
    name: str
    lang: str
    display_name: str
    supports_latest: bool = False

    @classmethod
    def from_dict(cls, d: dict) -> Source:
        return cls(
            id=d["id"],
            name=d["name"],
            lang=d.get("lang", ""),
            display_name=d.get("displayName", d.get("name", "")),
            supports_latest=d.get("supportsLatest", False),
        )


@dataclass
class Manga:
    id: int
    source_id: int
    url: str
    title: str
    status: str = "UNKNOWN"
    thumbnail_url: str | None = None
    in_library: bool = False
    author: str | None = None
    artist: str | None = None
    description: str | None = None
    genre: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: dict) -> Manga:
        return cls(
            id=d["id"],
            source_id=d.get("sourceId", 0),
            url=d.get("url", ""),
            title=d.get("title", ""),
            status=d.get("status", "UNKNOWN"),
            thumbnail_url=d.get("thumbnailUrl"),
            in_library=d.get("inLibrary", False),
            author=d.get("author"),
            artist=d.get("artist"),
            description=d.get("description"),
            genre=d.get("genre", []) or [],
        )


@dataclass
class Chapter:
    id: int
    url: str
    name: str
    chapter_number: float
    upload_date: int = 0
    is_read: bool = False
    is_downloaded: bool = False
    is_bookmarked: bool = False
    last_page_read: int = 0
    source_order: int = 0
    manga_id: int = 0
    page_count: int = 0

    @classmethod
    def from_dict(cls, d: dict) -> Chapter:
        return cls(
            id=d["id"],
            url=d.get("url", ""),
            name=d.get("name", ""),
            chapter_number=d.get("chapterNumber", 0.0),
            upload_date=d.get("uploadDate", 0),
            is_read=d.get("isRead", False),
            is_downloaded=d.get("isDownloaded", False),
            is_bookmarked=d.get("isBookmarked", False),
            last_page_read=d.get("lastPageRead", 0),
            source_order=d.get("sourceOrder", 0),
            manga_id=d.get("mangaId", 0),
            page_count=d.get("pageCount", 0),
        )


@dataclass
class SearchResult:
    mangas: list[Manga] = field(default_factory=list)
    has_next_page: bool = False

    @classmethod
    def from_dict(cls, d: dict) -> SearchResult:
        mangas = [Manga.from_dict(m) for m in d.get("mangas", [])]
        return cls(mangas=mangas, has_next_page=d.get("hasNextPage", False))
