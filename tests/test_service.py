"""Tests for suwayomi/service.py helpers (no network)."""

import asyncio
import copy

import pytest
from unittest.mock import AsyncMock, MagicMock

from suwayomi.models import Chapter
from suwayomi.service import (
    fmt_chapter_display,
    fmt_chapter_label,
    resolve_chapter,
)


def _ch(name: str, num: float) -> Chapter:
    return Chapter(id=1, url="", name=name, chapter_number=num,
                   source_order=1, upload_date=0)


class TestFmtChapterDisplay:

    def test_uses_name_when_available(self):
        ch = _ch("07卷附录", 7)
        assert fmt_chapter_display(ch) == "07卷附录"

    def test_uses_name_with_volume(self):
        ch = _ch("第8卷", 8)
        assert fmt_chapter_display(ch) == "第8卷"

    def test_uses_name_with_chapter(self):
        ch = _ch("第01话", 1)
        assert fmt_chapter_display(ch) == "第01话"

    def test_falls_back_to_number_with_话(self):
        ch = _ch("", 7)
        assert fmt_chapter_display(ch) == "第7话"

    def test_fallback_with_decimal(self):
        ch = _ch("", 38.5)
        assert fmt_chapter_display(ch) == "第38.5话"

    def test_fallback_with_nan(self):
        import math
        ch = _ch("", math.nan)
        assert fmt_chapter_display(ch) == "第?话"

    def test_handles_whitespace_name(self):
        ch = _ch("  ", 3)
        assert fmt_chapter_display(ch) == "第3话"

    def test_handles_extra_chapter_name(self):
        ch = _ch("07卷附录", 7)
        assert fmt_chapter_display(ch) == "07卷附录"

    def test_name_with_id_suffix_not_affected(self):
        ch = _ch("第5话后篇", 5)
        assert fmt_chapter_display(ch) == "第5话后篇"


class TestFmtChapterLabel:

    def test_uses_name_when_available(self):
        ch = _ch("第8卷", 8)
        assert fmt_chapter_label(ch, {}) == "#8 第8卷"

    def test_uses_name_with_dup_tag(self):
        ch = _ch("07卷附录", 7)
        assert fmt_chapter_label(ch, {7: 2}) == "#7 07卷附录 (ID:1)"


def _chapter(id: int, name: str, num: float) -> Chapter:
    return Chapter(id=id, url="", name=name, chapter_number=num,
                   source_order=1, upload_date=0)


class TestResolveChapter:

    def test_by_id_ascii_colon(self):
        chapters = [_chapter(100, "第1话", 1), _chapter(200, "第2话", 2)]
        target, err = resolve_chapter(chapters, "ID:200", "test", "阅读")
        assert err is None
        assert target is not None and target.id == 200

    def test_by_id_fullwidth_colon(self):
        chapters = [_chapter(100, "第1话", 1), _chapter(200, "第2话", 2)]
        target, err = resolve_chapter(chapters, "ID：200", "test", "阅读")
        assert err is None
        assert target is not None and target.id == 200

    def test_by_id_lowercase(self):
        chapters = [_chapter(100, "第1话", 1)]
        target, err = resolve_chapter(chapters, "id:100", "test", "阅读")
        assert err is None
        assert target is not None and target.id == 100

    def test_by_id_lowercase_fullwidth(self):
        chapters = [_chapter(100, "第1话", 1)]
        target, err = resolve_chapter(chapters, "id：100", "test", "阅读")
        assert err is None
        assert target is not None and target.id == 100

    def test_by_id_invalid_format(self):
        _, err = resolve_chapter([], "ID:abc", "test", "阅读")
        assert err is not None and "格式无效" in err

    def test_by_id_not_found(self):
        chapters = [_chapter(100, "第1话", 1)]
        _, err = resolve_chapter(chapters, "ID:999", "test", "阅读")
        assert err is not None and "未找到" in err

    def test_by_number(self):
        chapters = [_chapter(100, "第5话", 5)]
        target, err = resolve_chapter(chapters, "5", "test", "阅读")
        assert err is None
        assert target is not None and target.id == 100

    def test_invalid_number(self):
        _, err = resolve_chapter([], "abc", "test", "阅读")
        assert err is not None and "章节号无效" in err

    def test_by_number_with_prefix_suffix(self):
        chapters = [_chapter(100, "第5话", 5)]
        target, err = resolve_chapter(chapters, "第5话", "test", "阅读")
        assert err is None
        assert target is not None and target.id == 100

    def test_by_number_decimal_with_traditional_suffix(self):
        chapters = [_chapter(100, "第38.5话", 38.5)]
        target, err = resolve_chapter(chapters, "第38.5話", "test", "阅读")
        assert err is None
        assert target is not None and target.id == 100

    def test_missing_number_with_suffix_has_clean_message(self):
        chapters = [_chapter(100, "第5话", 5)]
        _, err = resolve_chapter(chapters, "第9话", "test", "阅读")
        assert err is not None
        assert "未找到第 9 话" in err
        assert "第第" not in err


class TestChapterTimestampConcurrency:

    @pytest.mark.asyncio
    async def test_concurrent_set_chapter_timestamp_preserves_all(self):
        from suwayomi.service import set_chapter_timestamp

        store: dict = {}

        async def get_kv(key, default=None):
            await asyncio.sleep(0.02)
            value = store.get(key, default)
            return copy.deepcopy(value)

        async def put_kv(key, value):
            await asyncio.sleep(0.02)
            store[key] = value

        await asyncio.gather(
            set_chapter_timestamp(get_kv, put_kv, 1),
            set_chapter_timestamp(get_kv, put_kv, 2),
        )
        data = store["suwayomi_chapter_timestamps"]
        assert "1" in data and "2" in data


class TestFmtDeliveryFailureMessage:

    def test_no_pages(self):
        from suwayomi.service import fmt_delivery_failure_message
        assert "暂无可用页面" in fmt_delivery_failure_message(0, "download", "none")

    def test_download_failed_with_auth(self):
        from suwayomi.service import fmt_delivery_failure_message
        msg = fmt_delivery_failure_message(30, "download", "jwt")
        assert "30" in msg and "jwt" in msg and "认证" in msg

    def test_download_failed_without_auth(self):
        from suwayomi.service import fmt_delivery_failure_message
        msg = fmt_delivery_failure_message(10, "download", "none")
        assert "10" in msg and "认证" not in msg

    def test_url_mode_with_auth(self):
        from suwayomi.service import fmt_delivery_failure_message
        msg = fmt_delivery_failure_message(5, "url", "basic")
        assert "URL 模式" in msg and "下载模式" in msg


class TestTtlCacheHelpers:

    def test_lookup_expires(self):
        from suwayomi.service import ttl_cache_lookup, ttl_cache_store
        cache = {}
        ttl_cache_store(cache, "a", 1, max_entries=4, now=100.0)
        assert ttl_cache_lookup(cache, "a", 10, now=105.0) == 1
        assert ttl_cache_lookup(cache, "a", 10, now=115.0) is None

    def test_store_evicts_oldest(self):
        from suwayomi.service import ttl_cache_lookup, ttl_cache_store
        cache = {}
        ttl_cache_store(cache, "a", 1, max_entries=2, now=1.0)
        ttl_cache_store(cache, "b", 2, max_entries=2, now=2.0)
        ttl_cache_store(cache, "c", 3, max_entries=2, now=3.0)
        assert ttl_cache_lookup(cache, "a", 10, now=4.0) is None
        assert ttl_cache_lookup(cache, "b", 10, now=4.0) == 2
        assert ttl_cache_lookup(cache, "c", 10, now=4.0) == 3


class TestSplitSearchQuery:

    def test_message_with_trailing_source_hint(self):
        """Full message keeps the trailing source hint lost by AstrBot's arg split."""
        from suwayomi.service import split_search_query
        kw, hint = split_search_query("/漫画 搜索 安达与岛村 再漫画", "安达与岛村")
        assert kw == "安达与岛村"
        assert hint == "再漫画"

    def test_message_without_source_hint(self):
        from suwayomi.service import split_search_query
        kw, hint = split_search_query("/漫画 搜索 安达与岛村", "安达与岛村")
        assert kw == "安达与岛村"
        assert hint == ""

    def test_falls_back_to_keyword_param(self):
        """When message parsing fails, use the AstrBot keyword param as-is."""
        from suwayomi.service import split_search_query
        kw, hint = split_search_query("", "安达与岛村 再漫画")
        assert kw == "安达与岛村"
        assert hint == "再漫画"

    def test_empty_message_and_keyword(self):
        from suwayomi.service import split_search_query
        kw, hint = split_search_query("", "")
        assert kw == ""
        assert hint == ""


class TestSearchBestMatch:

    @pytest.mark.asyncio
    async def test_default_sources_exclude_local_and_dedupe_variants(self):
        """Default multi-source search must skip the local source and prefer
        distinct extensions before MangaDex language variants."""
        from suwayomi.models import Source
        from suwayomi.service import search_best_match

        sources = [
            Source(id="0", name="Local", lang="en", display_name="Local source"),
            Source(id="1", name="MangaDex", lang="af", display_name="MangaDex (AF)"),
            Source(id="2", name="MangaDex", lang="sq", display_name="MangaDex (SQ)"),
            Source(id="3", name="CopyManga", lang="zh", display_name="拷贝漫画"),
            Source(id="4", name="Komiic", lang="zh", display_name="Komiic"),
            Source(id="5", name="ZaiManHua", lang="zh", display_name="再漫画"),
        ]
        client = MagicMock()
        client.get_sources = AsyncMock(return_value=sources)
        client.search_manga = AsyncMock(return_value=MagicMock(mangas=[]))

        manga, err = await search_best_match(client, {"default_source_id": 0}, "安达与岛村")

        assert err == "未找到匹配结果"
        assert manga is None
        called_ids = [c.args[0] for c in client.search_manga.await_args_list]
        assert called_ids == ["1", "3", "4"], (
            "first distinct extensions only, local source excluded, "
            f"got {called_ids}"
        )

    @pytest.mark.asyncio
    async def test_first_non_empty_result_wins(self):
        from suwayomi.models import Manga, Source
        from suwayomi.service import search_best_match

        sources = [
            Source(id="0", name="Local", lang="en", display_name="Local"),
            Source(id="1", name="MangaDex", lang="af", display_name="MangaDex (AF)"),
            Source(id="3", name="CopyManga", lang="zh", display_name="拷贝漫画"),
        ]
        found = Manga(id=42, source_id=3, url="", title="安达与岛村")
        client = MagicMock()
        client.get_sources = AsyncMock(return_value=sources)
        client.search_manga = AsyncMock(side_effect=[
            MagicMock(mangas=[]),
            MagicMock(mangas=[found]),
        ])

        manga, err = await search_best_match(client, {"default_source_id": 0}, "安达与岛村")

        assert err is None
        assert manga is found
