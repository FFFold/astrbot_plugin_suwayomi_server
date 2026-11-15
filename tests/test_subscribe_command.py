"""Unit tests for /漫画 订阅 reference forms (no network)."""
from unittest.mock import AsyncMock, MagicMock

import pytest

from plugin_pkg.main import SuwayomiPlugin
from plugin_pkg.suwayomi.client import SuwayomiError
from plugin_pkg.suwayomi.models import Manga

UMO = "aiocqhttp:group:g1"


def _manga(mid=151, title="安达与岛村"):
    return Manga(id=mid, source_id=2, url="", title=title, status="ONGOING")


def _plugin():
    plugin = SuwayomiPlugin.__new__(SuwayomiPlugin)
    plugin.client = MagicMock()
    plugin.client.get_sources = AsyncMock(return_value=[])
    plugin.sub_mgr = MagicMock()
    plugin.sub_mgr.subscribe = AsyncMock()
    plugin.sub_mgr.update_latest_chapter = AsyncMock()
    plugin.config = {"result_cards_enabled": False}
    plugin._search_cache = {}
    return plugin


def _event(message):
    event = MagicMock()
    event.unified_msg_origin = UMO
    event.message_str = message
    event.plain_result = MagicMock(side_effect=lambda text: text)
    event.chain_result = MagicMock(side_effect=lambda chain: chain)
    event.send = AsyncMock()
    return event


@pytest.mark.asyncio
async def test_subscribe_accepts_id_prefix(monkeypatch):
    plugin = _plugin()
    plugin.client.get_manga = AsyncMock(return_value=_manga(151))
    monkeypatch.setattr(
        "plugin_pkg.main.get_or_fetch_chapters", AsyncMock(return_value=[])
    )
    event = _event("/漫画 订阅 ID:151")

    results = [m async for m in plugin.subscribe_manga(event, "ID:151")]

    plugin.sub_mgr.subscribe.assert_awaited_once_with(151, "安达与岛村", 2, UMO)
    assert "已订阅" in results[0]


@pytest.mark.asyncio
async def test_subscribe_still_accepts_search_index(monkeypatch):
    plugin = _plugin()
    plugin._search_cache[UMO] = (__import__("time").time(), {"3": _manga(302)})
    monkeypatch.setattr(
        "plugin_pkg.main.get_or_fetch_chapters", AsyncMock(return_value=[])
    )
    event = _event("/漫画 订阅 3")

    results = [m async for m in plugin.subscribe_manga(event, "3")]

    plugin.sub_mgr.subscribe.assert_awaited_once_with(302, "安达与岛村", 2, UMO)
    assert "已订阅" in results[0]


@pytest.mark.asyncio
async def test_subscribe_missing_id_is_reported(monkeypatch):
    plugin = _plugin()
    plugin.client.get_manga = AsyncMock(side_effect=SuwayomiError("not found"))
    event = _event("/漫画 订阅 ID:999")

    results = [m async for m in plugin.subscribe_manga(event, "ID:999")]

    plugin.sub_mgr.subscribe.assert_not_awaited()
    assert "未找到 ID:999" in results[0]


@pytest.mark.asyncio
async def test_subscribe_name_is_rejected_with_guidance():
    plugin = _plugin()
    event = _event("/漫画 订阅 安达与岛村")

    results = [m async for m in plugin.subscribe_manga(event, "安达与岛村")]

    plugin.sub_mgr.subscribe.assert_not_awaited()
    assert "搜索结果编号" in results[0] and "ID:151" in results[0]
