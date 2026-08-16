"""Tests for suwayomi/updater.py (no network)."""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from suwayomi.client import SuwayomiError
from suwayomi.models import Chapter, Manga
from suwayomi.updater import check_updates


class FakePlugin:
    def __init__(self):
        self._store = {}

    async def get_kv_data(self, key, default=None):
        return self._store.get(key, default)

    async def put_kv_data(self, key, value):
        self._store[key] = value


def _chapters(manga_id, ids):
    return [
        Chapter(id=cid, url="", name=f"第{cid}话", chapter_number=float(cid),
                source_order=cid, upload_date=0, manga_id=manga_id)
        for cid in ids
    ]


class CountingClient:
    def __init__(self, chapters_by_manga, delay=0.05):
        self._chapters = chapters_by_manga
        self.delay = delay
        self.active = 0
        self.max_active = 0
        self.fetch_calls = 0

    async def fetch_chapters(self, manga_id):
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        self.fetch_calls += 1
        await asyncio.sleep(self.delay)
        self.active -= 1
        return self._chapters[manga_id]

    async def get_manga(self, manga_id):
        raise SuwayomiError("skip title sync")

    async def update_library(self):
        return None


def _context():
    ctx = MagicMock()
    ctx.send_message = AsyncMock()
    return ctx


def _make_sub_mgr(plugin):
    from utils.subscription import SubscriptionManager
    return SubscriptionManager(plugin)


def _config():
    return {"chapter_cache_hours": -1}


@pytest.mark.asyncio
async def test_check_updates_no_subscriptions_does_not_record_time():
    client = CountingClient({})
    plugin = FakePlugin()
    sub_mgr = _make_sub_mgr(plugin)
    summary = await check_updates(
        client, sub_mgr, _context(), _config(),
        plugin.get_kv_data, plugin.put_kv_data, asyncio.Lock(),
        AsyncMock(), AsyncMock(),
    )
    assert "没有订阅" in summary
    assert "suwayomi_last_update_check" not in plugin._store


@pytest.mark.asyncio
async def test_check_updates_no_updates_records_last_check():
    client = CountingClient({1: _chapters(1, [1, 2])})
    plugin = FakePlugin()
    sub_mgr = _make_sub_mgr(plugin)
    await sub_mgr.subscribe(1, "T1", 1, "u1")
    await sub_mgr.update_latest_chapter(1, 2)
    summary = await check_updates(
        client, sub_mgr, _context(), _config(),
        plugin.get_kv_data, plugin.put_kv_data, asyncio.Lock(),
        AsyncMock(), AsyncMock(),
    )
    assert "暂无更新" in summary
    assert plugin._store["suwayomi_last_update_check"] > 0


@pytest.mark.asyncio
async def test_check_updates_processes_parallel():
    client = CountingClient({i: _chapters(i, [i]) for i in range(1, 9)})
    plugin = FakePlugin()
    sub_mgr = _make_sub_mgr(plugin)
    for i in range(1, 9):
        await sub_mgr.subscribe(i, f"T{i}", 1, "u1")
    ctx = _context()
    summary = await check_updates(
        client, sub_mgr, ctx, _config(),
        plugin.get_kv_data, plugin.put_kv_data, asyncio.Lock(),
        AsyncMock(), AsyncMock(),
    )
    assert client.fetch_calls == 8
    assert client.max_active >= 2
    assert "8 部漫画更新" in summary
    # messages are merged per subscriber session: all 8 mangas share umo "u1"
    assert ctx.send_message.await_count == 1


@pytest.mark.asyncio
async def test_check_updates_survives_single_manga_failure():
    async def broken_fetch(manga_id):
        if manga_id == 2:
            raise SuwayomiError("source exploded")
        return _chapters(manga_id, [manga_id])

    client = CountingClient({1: [], 2: [], 3: []})
    client.fetch_chapters = broken_fetch
    plugin = FakePlugin()
    sub_mgr = _make_sub_mgr(plugin)
    for i in (1, 2, 3):
        await sub_mgr.subscribe(i, f"T{i}", 1, "u1")
    ctx = _context()
    summary = await check_updates(
        client, sub_mgr, ctx, _config(),
        plugin.get_kv_data, plugin.put_kv_data, asyncio.Lock(),
        AsyncMock(), AsyncMock(),
    )
    assert "2 部漫画更新" in summary
    assert "T1" in summary and "T3" in summary


@pytest.mark.asyncio
async def test_check_updates_skips_corrupted_subscription_key():
    """A non-numeric subscription key (corrupted KV) must not abort the whole scan."""
    plugin = FakePlugin()
    plugin._store["suwayomi_subscriptions"] = {
        "abc": {
            "title": "corrupted",
            "source_id": 1,
            "latest_chapter_id": 0,
            "subscribers": {"u1": {"push_enabled": False}},
        },
        "2": {
            "title": "T2",
            "source_id": 1,
            "latest_chapter_id": 0,
            "subscribers": {"u1": {"push_enabled": False}},
        },
    }
    sub_mgr = _make_sub_mgr(plugin)
    client = CountingClient({2: _chapters(2, [2])})
    summary = await check_updates(
        client, sub_mgr, _context(), _config(),
        plugin.get_kv_data, plugin.put_kv_data, asyncio.Lock(),
        AsyncMock(), AsyncMock(),
    )
    assert "1 部漫画更新" in summary
    assert "T2" in summary


@pytest.mark.asyncio
async def test_check_updates_skips_non_dict_subscription_value():
    """A subscription entry whose value is not a dict must not abort the scan."""
    plugin = FakePlugin()
    plugin._store["suwayomi_subscriptions"] = {
        "1": "not-a-dict",
        "2": {
            "title": "T2",
            "source_id": 1,
            "latest_chapter_id": 0,
            "subscribers": {"u1": {"push_enabled": False}},
        },
    }
    sub_mgr = _make_sub_mgr(plugin)
    client = CountingClient({2: _chapters(2, [2])})
    summary = await check_updates(
        client, sub_mgr, _context(), _config(),
        plugin.get_kv_data, plugin.put_kv_data, asyncio.Lock(),
        AsyncMock(), AsyncMock(),
    )
    assert "1 部漫画更新" in summary
    assert "T2" in summary


@pytest.mark.asyncio
async def test_check_updates_all_failed_reports_error_without_timestamp():
    """When every subscription check errors, report failure and do not stamp a fresh check time."""
    async def always_broken(manga_id):
        raise SuwayomiError("server down")

    client = CountingClient({1: [], 2: []})
    client.fetch_chapters = always_broken
    plugin = FakePlugin()
    sub_mgr = _make_sub_mgr(plugin)
    for i in (1, 2):
        await sub_mgr.subscribe(i, f"T{i}", 1, "u1")
    summary = await check_updates(
        client, sub_mgr, _context(), _config(),
        plugin.get_kv_data, plugin.put_kv_data, asyncio.Lock(),
        AsyncMock(), AsyncMock(),
    )
    assert "检查出错" in summary or "失败" in summary
    assert "suwayomi_last_update_check" not in plugin._store


def _update_manga(thumbnail="/api/v1/manga/1/thumbnail"):
    return Manga(id=1, source_id=1, url="", title="T1", status="ONGOING",
                 thumbnail_url=thumbnail)


@pytest.mark.asyncio
async def test_check_updates_sends_card_when_render_fn_succeeds():
    client = CountingClient({1: _chapters(1, [1, 2])})
    client.get_manga = AsyncMock(return_value=_update_manga())
    plugin = FakePlugin()
    sub_mgr = _make_sub_mgr(plugin)
    await sub_mgr.subscribe(1, "T1", 1, "u1")
    await sub_mgr.update_latest_chapter(1, 1)
    ctx = _context()

    async def render_fn(umo, items, heading):
        return "/tmp/update-card.jpg"

    with patch("suwayomi.updater.Comp.Image.fromFileSystem") as mock_img:
        mock_img.return_value = MagicMock()
        await check_updates(
            client, sub_mgr, ctx, _config(),
            plugin.get_kv_data, plugin.put_kv_data, asyncio.Lock(),
            AsyncMock(), AsyncMock(),
            render_update_card_fn=render_fn,
        )
    mock_img.assert_called_once_with("/tmp/update-card.jpg")
    assert ctx.send_message.await_count == 1


@pytest.mark.asyncio
async def test_check_updates_falls_back_to_text_when_render_fails():
    client = CountingClient({1: _chapters(1, [1, 2])})
    client.get_manga = AsyncMock(return_value=_update_manga())
    plugin = FakePlugin()
    sub_mgr = _make_sub_mgr(plugin)
    await sub_mgr.subscribe(1, "T1", 1, "u1")
    await sub_mgr.update_latest_chapter(1, 1)
    ctx = _context()

    async def render_fn(umo, items, heading):
        return None

    with patch("suwayomi.updater.Comp.Image.fromFileSystem") as mock_img:
        mock_img.return_value = MagicMock()
        await check_updates(
            client, sub_mgr, ctx, _config(),
            plugin.get_kv_data, plugin.put_kv_data, asyncio.Lock(),
            AsyncMock(), AsyncMock(),
            render_update_card_fn=render_fn,
        )
    mock_img.assert_not_called()
    assert ctx.send_message.await_count == 1  # 文本消息回退


@pytest.mark.asyncio
async def test_check_updates_build_update_items_include_thumbnail():
    client = CountingClient({1: _chapters(1, [1, 2])})
    client.get_manga = AsyncMock(return_value=_update_manga())
    plugin = FakePlugin()
    sub_mgr = _make_sub_mgr(plugin)
    await sub_mgr.subscribe(1, "T1", 1, "u1")
    await sub_mgr.update_latest_chapter(1, 1)
    ctx = _context()
    seen = {}

    async def render_fn(umo, items, heading):
        seen["items"] = items
        seen["heading"] = heading
        return "/tmp/c.jpg"

    with patch("suwayomi.updater.Comp.Image.fromFileSystem") as mock_img:
        mock_img.return_value = MagicMock()
        await check_updates(
            client, sub_mgr, ctx, _config(),
            plugin.get_kv_data, plugin.put_kv_data, asyncio.Lock(),
            AsyncMock(), AsyncMock(),
            render_update_card_fn=render_fn,
        )
    assert seen["items"][0]["thumbnail_url"] == "/api/v1/manga/1/thumbnail"
    assert seen["items"][0]["title"] == "T1"
    assert seen["items"][0]["status"] == "ONGOING"
