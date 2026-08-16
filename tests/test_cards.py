"""Unit tests for suwayomi/cards.py (no network)."""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import plugin_pkg.utils.downloader as downloader_mod
import plugin_pkg.utils.pusher as pusher_mod
import pytest
from plugin_pkg.suwayomi.cards import (
    CHAPTER_LINES_PER_CARD,
    MAX_CHAPTER_CARDS,
    CardCache,
    build_batch_card,
    build_chapter_cards,
    build_search_card,
    build_subscribe_confirm_card,
    build_subscriptions_card,
    build_update_card,
    embed_covers,
    render_card,
    render_card_cached,
    resolve_cover_url,
)


def _manga(title="咒术回战", status="ONGOING", thumbnail="/api/v1/manga/1/thumbnail"):
    return {"title": title, "status": status, "thumbnail_url": thumbnail}


def test_build_search_card_escapes_and_numbers_rows():
    data = build_search_card(
        [
            {"index": 1, "title": "咒术回战", "status": "ONGOING", "source": "拷贝漫画", "thumbnail_url": "/a"},
            {"index": 2, "title": "鬼灭<之刃", "status": "COMPLETED", "source": "拷贝漫画", "thumbnail_url": "/b"},
        ],
        subtitle="拷贝漫画 · 2 条",
        footer="回复「漫画 订阅 <编号>」订阅",
    )
    assert data["card_type"] == "search"
    assert data["rows"][0]["index"] == 1
    assert data["rows"][0]["detail"] == "连载中 · 拷贝漫画"
    assert data["rows"][1]["title"] == "鬼灭&lt;之刃"
    assert data["footer"] == "回复「漫画 订阅 &lt;编号&gt;」订阅"
    # thumbnail_url 原样保留供 embed_covers 使用
    assert data["rows"][0]["thumbnail_url"] == "/a"


def test_build_subscribe_confirm_card():
    data = build_subscribe_confirm_card(
        {"title": "鬼灭之刃", "status": "COMPLETED", "thumbnail_url": "/c"},
        source_name="拷贝漫画",
        footer="有新章节时会推送通知",
    )
    assert data["card_type"] == "confirm"
    assert data["title"] == "鬼灭之刃"
    assert data["status"] == "已完结"
    assert data["status_class"] == "status-completed"
    assert "ID" in data["meta"] and "拷贝漫画" in data["meta"]


def test_build_update_card_multi():
    data = build_update_card(
        [
            {"title": "咒术回战", "status": "ONGOING", "chapters": ["#251 新的一页", "#252 决战"],
             "read_hint": "「漫画 阅读 咒术回战 252」", "thumbnail_url": "/d"},
            {"title": "鬼灭之刃", "status": "COMPLETED", "chapters": ["#205"],
             "read_hint": "「漫画 阅读 鬼灭之刃 205」", "thumbnail_url": "/e"},
        ],
        heading="📢 2 部漫画更新了",
    )
    assert data["heading"] == "📢 2 部漫画更新了"
    assert data["items"][0]["status"] == "连载中"
    assert data["items"][1]["status_class"] == "status-completed"
    assert data["items"][0]["chapters"][0] == "#251 新的一页"


def test_build_subscriptions_card():
    data = build_subscriptions_card([
        {"title": "咒术回战", "detail": "连载中 - 拷贝漫画 · 🔔 推送开 · ID: 1", "thumbnail_url": "/a"},
    ])
    assert data["card_type"] == "subscriptions"
    assert data["rows"][0]["title"] == "咒术回战"


def test_build_batch_card_marks():
    data = build_batch_card(
        [
            {"status": "ok", "title": "咒术回战", "detail": "连载中 - 拷贝漫画", "thumbnail_url": "/f"},
            {"status": "exists", "title": "鬼灭之刃", "detail": "已完结 - 拷贝漫画（已订阅）", "thumbnail_url": "/g"},
            {"status": "fail", "title": "海贼王", "detail": "未找到匹配结果", "thumbnail_url": None},
        ],
        summary="1 新增, 1 已存在, 1 失败",
    )
    icons = {row["icon"] for row in data["rows"]}
    assert icons == {"✓", "⏭", "✕"}
    assert {row["mark_class"] for row in data["rows"]} == {"mark-ok", "mark-skip", "mark-fail"}
    assert data["rows"][2]["thumbnail_url"] is None


def test_build_chapter_cards_single_header_only():
    cards, tail = build_chapter_cards(
        {"title": "咒术回战", "cover_data_url": None, "meta": "拷贝漫画 · 3 话",
         "tags": ["连载中"], "hint": "「漫画 章节 咒术回战 --刷新」"},
        ["#1", "#2", "#3"],
    )
    assert len(cards) == 1
    assert tail == []
    assert cards[0]["is_continuation"] is False
    # 三列
    assert len(cards[0]["chunks"]) == 3
    assert sum(len(c) for c in cards[0]["chunks"]) == 3
    # 标题保留
    assert cards[0]["title"] == "咒术回战"


def test_build_chapter_cards_chunks_by_constant():
    lines = [f"#{i} 章" for i in range(1, CHAPTER_LINES_PER_CARD * 2 + 1)]
    cards, tail = build_chapter_cards({"title": "X", "cover_data_url": None}, lines)
    assert len(cards) == 2
    assert tail == []
    assert cards[1]["is_continuation"] is True
    assert cards[1]["continuation"] == "章节续 (2/2)"
    # 每张卡的行数不超过 per-card 常量
    for card in cards:
        total = sum(len(c) for c in card["chunks"])
        assert total <= CHAPTER_LINES_PER_CARD


def test_build_chapter_cards_tail_and_cap():
    lines = [f"#{i}" for i in range(1, CHAPTER_LINES_PER_CARD * (MAX_CHAPTER_CARDS + 1) + 10)]
    cards, tail = build_chapter_cards({"title": "X", "cover_data_url": None}, lines)
    assert len(cards) == MAX_CHAPTER_CARDS
    assert len(tail) == len(lines) - CHAPTER_LINES_PER_CARD * MAX_CHAPTER_CARDS


def test_build_chapter_cards_escapes_lines():
    lines = ["#1 章 & 节", "#2 <b>x</b>"]
    cards, tail = build_chapter_cards({"title": "X", "cover_data_url": None}, lines)
    flat = [line for col in cards[0]["chunks"] for line in col]
    assert "章 &amp; 节" in flat[0]["main"]
    assert "<b>" not in "".join(x["main"] + x["id"] for x in flat)
    # tail 返回原始行（用于纯文本，不转义）
    cards2, tail2 = build_chapter_cards({"title": "X", "cover_data_url": None}, ["#1 & x"] * 600)
    assert tail2 == ["#1 & x"] * (600 - CHAPTER_LINES_PER_CARD * MAX_CHAPTER_CARDS)


def test_build_chapter_cards_columns_keep_reading_order():
    lines = [f"#{i}" for i in range(1, 11)]
    cards, tail = build_chapter_cards({"title": "X", "cover_data_url": None}, lines)
    chunks = cards[0]["chunks"]
    # 连续切片而非轮询：列 1 = #1..#4，列 2 = #5..#8，列 3 = #9..#10
    flat = [x["main"] for col in chunks for x in col]
    assert flat == ["#1", "#2", "#3", "#4", "#5", "#6", "#7", "#8", "#9", "#10"]
    assert [x["main"] for x in chunks[0]] == ["#1", "#2", "#3", "#4"]


def test_build_chapter_cards_splits_id_tag():
    cards, tail = build_chapter_cards(
        {"title": "X", "cover_data_url": None},
        ["#1 单行本：第01卷 (ID:2539)", "#2 普通章节", "#1 (ID:7)"],
    )
    flat = [x for col in cards[0]["chunks"] for x in col]
    by_main = {x["main"]: x["id"] for x in flat}
    assert by_main["#1 单行本：第01卷"] == "(ID:2539)"
    assert by_main["#2 普通章节"] == ""
    assert by_main["#1"] == "(ID:7)"


def test_build_chapter_cards_empty_lines_returns_header():
    cards, tail = build_chapter_cards({"title": "X", "cover_data_url": None}, [])
    assert len(cards) == 1
    assert tail == []


class FakeClient:
    def __init__(self):
        self.server_url = "http://localhost:4567"
        self.auth_headers = {"Authorization": "Bearer tok"}

    def build_image_url(self, rel):
        return f"{self.server_url}{rel}"


def _pillow_cover(path):
    from PIL import Image
    img = Image.new("RGB", (300, 400), (200, 100, 50))
    img.save(path, format="JPEG")
    return path


def test_resolve_cover_url_relative_uses_auth():
    client = FakeClient()
    url, headers = resolve_cover_url(client, "/api/v1/manga/1/thumbnail")
    assert url == "http://localhost:4567/api/v1/manga/1/thumbnail"
    assert headers == {"Authorization": "Bearer tok"}


def test_resolve_cover_url_external_no_auth():
    client = FakeClient()
    url, headers = resolve_cover_url(client, "https://cdn.example.com/c.jpg")
    assert url == "https://cdn.example.com/c.jpg"
    assert headers is None


def test_resolve_cover_url_none():
    client = FakeClient()
    assert resolve_cover_url(client, None) == (None, None)


@patch.object(downloader_mod, "download_images", new_callable=AsyncMock)
@patch.object(pusher_mod, "schedule_cleanup")
@pytest.mark.asyncio
async def test_embed_covers_success(mock_cleanup, mock_download, tmp_path):
    cover = tmp_path / "cover.jpg"
    _pillow_cover(str(cover))
    mock_download.return_value = ([str(cover), str(cover)], tmp_path)
    client = FakeClient()
    items = [{"title": "A", "thumbnail_url": "/a"}, {"title": "B", "thumbnail_url": "/b"}]
    result = await embed_covers(client, items, custom_tmp="", retries=3, concurrency=2)
    assert len(result) == 2
    assert result[0]["cover_data_url"].startswith("data:image/jpeg;base64,")
    assert result[1]["cover_data_url"].startswith("data:image/jpeg;base64,")
    assert "thumbnail_url" not in result[0]
    mock_cleanup.assert_called_once()


@patch.object(downloader_mod, "download_images", new_callable=AsyncMock)
@patch.object(pusher_mod, "schedule_cleanup")
@pytest.mark.asyncio
async def test_embed_covers_partial_failure_placeholder(mock_cleanup, mock_download):
    mock_download.return_value = (["/missing.jpg", ""], MagicMock())
    client = FakeClient()
    result = await embed_covers(client, [{"title": "A", "thumbnail_url": "/a"}], retries=3)
    assert result[0]["cover_data_url"] is None


@patch.object(downloader_mod, "download_images", new_callable=AsyncMock)
@patch.object(pusher_mod, "schedule_cleanup")
@pytest.mark.asyncio
async def test_embed_covers_download_error_no_raise(mock_cleanup, mock_download):
    mock_download.side_effect = OSError("boom")
    client = FakeClient()
    items = [{"title": "A", "thumbnail_url": "/a"}, {"title": "B", "thumbnail_url": "/b"}]
    result = await embed_covers(client, items, retries=3)
    assert all(item["cover_data_url"] is None for item in result)


@patch.object(downloader_mod, "download_images", new_callable=AsyncMock)
@patch.object(pusher_mod, "schedule_cleanup")
@pytest.mark.asyncio
async def test_embed_covers_skips_download_when_no_thumbnail(mock_cleanup, mock_download):
    client = FakeClient()
    items = [{"title": "A", "thumbnail_url": None}, {"title": "B", "thumbnail_url": ""}]
    result = await embed_covers(client, items, retries=3)
    assert result[0]["cover_data_url"] is None
    assert result[1]["cover_data_url"] is None
    mock_download.assert_not_called()
    mock_cleanup.assert_not_called()


def test_embed_covers_bad_image_no_raise(tmp_path):
    from plugin_pkg.suwayomi.cards import _cover_data_url
    bad = tmp_path / "bad.jpg"
    bad.write_bytes(b"not an image")
    assert _cover_data_url(str(bad)) is None


@pytest.mark.asyncio
async def test_render_card_returns_path():
    captured = {}

    async def fake_html_render(tmpl, data, return_url, options):
        captured["options"] = options
        return "/tmp/card.jpg"

    path = await render_card(fake_html_render, {"card_type": "search"}, timeout=10)
    assert path == "/tmp/card.jpg"
    # 高清输出：880px 画布 × 1.8 设备像素比 → 约 1584px 物理像素，手机 2x/3x 屏文字不糊
    assert captured["options"]["viewport_width"] == 880
    assert captured["options"]["device_scale_factor_level"] == "ultra"
    assert captured["options"]["quality"] == 95
    # 视口高度小于内容高度，避免 scrollHeight 被默认 720 撑高导致底部空白
    assert captured["options"]["viewport_height"] == 100


@pytest.mark.asyncio
async def test_render_card_failure_returns_none():
    async def boom(tmpl, data, return_url, options):
        raise RuntimeError("endpoint down")

    assert await render_card(boom, {"card_type": "search"}, timeout=10) is None


@pytest.mark.asyncio
async def test_render_card_timeout_returns_none():
    async def slow(tmpl, data, return_url, options):
        await asyncio.sleep(5)

    assert await render_card(slow, {"card_type": "search"}, timeout=0.01) is None


def test_card_cache_hit_and_miss():
    cache = CardCache(ttl=600)
    data = {"card_type": "search", "rows": []}
    assert cache.get(data) is None
    cache.put(data, "/a")
    assert cache.get(data) == "/a"
    assert cache.get({"card_type": "search", "rows": [1]}) is None


def test_card_cache_ttl_expiry():
    cache = CardCache(ttl=10)
    data = {"card_type": "search"}
    cache.put(data, "/a", now=100)
    assert cache.get(data, now=105) == "/a"
    assert cache.get(data, now=111) is None


def test_card_cache_key_ignores_key_order():
    cache = CardCache()
    cache.put({"a": 1, "b": 2}, "/x")
    assert cache.get({"b": 2, "a": 1}) == "/x"


def test_card_cache_max_entries_evicts_oldest():
    cache = CardCache(ttl=600, max_entries=2)
    cache.put({"k": 1}, "/1", now=1)
    cache.put({"k": 2}, "/2", now=2)
    cache.put({"k": 3}, "/3", now=3)
    assert cache.get({"k": 1}, now=4) is None
    assert cache.get({"k": 2}, now=4) == "/2"


@pytest.mark.asyncio
async def test_render_card_cached_skips_render_on_hit():
    cache = CardCache(ttl=600)
    calls = 0

    async def fake_html_render(tmpl, data, return_url, options):
        nonlocal calls
        calls += 1
        return "/tmp/card.jpg"

    data = {"card_type": "search"}
    first = await render_card_cached(cache, fake_html_render, data, timeout=10)
    second = await render_card_cached(cache, fake_html_render, data, timeout=10)
    assert first == second == "/tmp/card.jpg"
    assert calls == 1
