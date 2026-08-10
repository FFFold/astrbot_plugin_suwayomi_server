"""Tests for suwayomi/updater.py (no network)."""
import asyncio

import pytest
from unittest.mock import AsyncMock, MagicMock

from suwayomi.client import SuwayomiError
from suwayomi.models import Chapter
from suwayomi.updater import LAST_CHECK_KV_KEY, check_updates


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
