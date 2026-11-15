"""Unit tests for resolve_manga reference parsing (no network)."""
from unittest.mock import AsyncMock, MagicMock

import pytest

from suwayomi.client import SuwayomiError
from suwayomi.models import Manga, Source
from suwayomi.service import resolve_manga

UMO = "aiocqhttp:group:g1"


def _manga(mid=151, title="安达与岛村"):
    return Manga(id=mid, source_id=2, url="", title=title, status="ONGOING")


class _Client:
    def __init__(self, mangas=None, by_title=None):
        self._mangas = mangas or {}
        self._by_title = by_title or []

    async def get_manga(self, manga_id):
        if int(manga_id) in self._mangas:
            return self._mangas[int(manga_id)]
        raise SuwayomiError("not found")

    async def search_manga_by_title(self, title, limit=10):
        return list(self._by_title)

    async def get_sources(self):
        return [Source(id="2", name="mh", lang="zh", display_name="拷贝漫画")]


def _subs(titles=()):
    sub_mgr = MagicMock()
    sub_mgr.get_subscriptions = AsyncMock(
        return_value=[{"manga_id": 1, "title": t} for t in titles]
    )
    return sub_mgr


@pytest.mark.asyncio
async def test_index_hit_returns_cached_manga_without_lookup():
    cached = _manga(302, "安达与岛村官方同人集")
    client = _Client()
    manga, err = await resolve_manga(
        client, _subs(), UMO, "3", "阅读",
        index_lookup=lambda umo, key: (cached, 5),
    )
    assert err is None and manga is cached


@pytest.mark.asyncio
async def test_index_miss_but_id_exists_points_to_id_syntax():
    client = _Client(mangas={3: _manga(3, "某漫画")})
    manga, err = await resolve_manga(
        client, _subs(), UMO, "3", "阅读",
        index_lookup=lambda umo, key: (None, 0),
    )
    assert manga is None
    assert "是漫画 ID" in err and "ID:3" in err and "阅读" in err


@pytest.mark.asyncio
async def test_index_out_of_range_reports_display_range():
    client = _Client()
    manga, err = await resolve_manga(
        client, _subs(), UMO, "9", "章节",
        index_lookup=lambda umo, key: (None, 5),
    )
    assert manga is None
    assert "1–5" in err and "9" in err


@pytest.mark.asyncio
async def test_index_without_cache_explains_ttl():
    client = _Client()
    manga, err = await resolve_manga(
        client, _subs(), UMO, "2", "下载",
        index_lookup=lambda umo, key: (None, 0),
    )
    assert manga is None
    assert "10 分钟" in err and "漫画 搜索" in err


@pytest.mark.asyncio
async def test_id_ref_resolves_and_does_not_fall_through_to_names():
    client = _Client(mangas={151: _manga(151)})
    manga, err = await resolve_manga(
        client, _subs(["安达与岛村"]), UMO, "ID:151", "阅读"
    )
    assert err is None and manga.id == 151


@pytest.mark.asyncio
async def test_id_ref_missing_reports_id_not_found():
    client = _Client()
    manga, err = await resolve_manga(
        client, _subs(["安达与岛村"]), UMO, "id：999", "阅读"
    )
    assert manga is None and "ID:999" in err and "未找到" in err


@pytest.mark.asyncio
async def test_id_probe_failure_falls_back_to_ttl_message():
    client = _Client()
    client.get_manga = AsyncMock(side_effect=SuwayomiError("boom"))
    manga, err = await resolve_manga(
        client, _subs(), UMO, "4", "阅读",
        index_lookup=lambda umo, key: (None, 0),
    )
    assert manga is None and "10 分钟" in err


@pytest.mark.asyncio
async def test_numeric_title_is_treated_as_index_not_crash():
    client = _Client()
    manga, err = await resolve_manga(
        client, _subs(), UMO, "86", "章节",
        index_lookup=lambda umo, key: (None, 0),
    )
    assert manga is None and "漫画 搜索" in err


@pytest.mark.asyncio
async def test_index_without_callback_reports_no_search_results():
    client = _Client()
    manga, err = await resolve_manga(client, _subs(), UMO, "2", "阅读")
    assert manga is None and "漫画 搜索" in err


@pytest.mark.asyncio
async def test_name_path_unchanged_and_multi_result_uses_id_prefix():
    client = _Client(by_title=[_manga(151), _manga(302, "安达与岛村官方同人集")])
    manga, err = await resolve_manga(
        client, _subs(["别的漫画"]), UMO, "安达与岛村", "章节"
    )
    assert manga is None
    assert "ID:151" in err and "ID:302" in err
    assert "ID 151" not in err
